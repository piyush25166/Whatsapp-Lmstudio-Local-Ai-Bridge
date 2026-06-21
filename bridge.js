const { Client, LocalAuth } = require('whatsapp-web.js');
const axios = require('axios');

// ==========================================
// ANTI-CRASH PROTOCOLS
// ==========================================
process.on('uncaughtException', err => {
    console.error('[FATAL EXCEPTION]', err);
    sendLogToUI(`<span class='text-red-500'>[FATAL] Node crash prevented: ${err.message}</span>`);
});
process.on('unhandledRejection', err => {
    console.error('[FATAL REJECTION]', err);
    sendLogToUI(`<span class='text-red-500'>[FATAL] Promise rejection: ${err.message}</span>`);
});

console.log("=> Booting Background Bridge Engine...");

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        handleSIGINT: false,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
    }
});

const WEBUI_API = 'http://127.0.0.1:5000';

async function sendLogToUI(message) {
    console.log(message.replace(/<[^>]*>?/gm, '')); // Strip HTML for the local terminal
    try { await axios.post(`${WEBUI_API}/api/bridge-log`, { log: message }); } catch (e) {}
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

client.on('qr', async (qr) => {
    console.log("=> QR Code captured. Broadcasting to UI...");
    try { await axios.post(`${WEBUI_API}/api/update-qr`, { qr }); } catch (e) {}
});

client.on('ready', async () => {
    try {
        await axios.post(`${WEBUI_API}/api/update-status`, { status: 'Connected' });
        await sendLogToUI("<span class='text-green-400'>[BRIDGE] Linked with WhatsApp Web.</span>");
    } catch (e) {}
});

client.on('message', async msg => {
    // Ignore self-messages and non-text media
    if (msg.fromMe || msg.type !== 'chat') return;

    try {
        // Master kill switch - admin panel "bot enabled" toggle
        let botEnabled = true;
        try {
            const enabledRes = await axios.get(`${WEBUI_API}/api/check-bot-enabled`);
            botEnabled = enabledRes.data.enabled;
        } catch (e) { /* if the panel is down, fail open so bot keeps working locally */ }
        if (!botEnabled) return;

        const chat = await msg.getChat();
        const contact = await msg.getContact();
        const senderName = contact.pushname || contact.name || contact.number;
        const chatId = msg.from;
        const isGroup = chat.isGroup;
        const displayName = isGroup ? (chat.name || chatId) : senderName;

        // Contact gate - block list + observer mode, also registers/updates
        // this contact in the admin panel's contact list even if it's the
        // first message. Checked BEFORE the reply-trigger logic so a
        // blocked group/contact never gets logged or replied to at all.
        let blocked = false;
        let observerMode = false;
        try {
            const gateRes = await axios.post(`${WEBUI_API}/api/check-contact`, {
                chat_id: chatId,
                display_name: displayName,
                is_group: isGroup,
            });
            blocked = gateRes.data.blocked;
            observerMode = gateRes.data.observer;
        } catch (e) { /* fail open if panel unreachable */ }

        if (blocked) {
            await sendLogToUI(`[BRIDGE] Ignored message from blocked contact: ${displayName}`);
            return;
        }

        // Observer mode: log everything, reply to nothing, no typing
        // indicator ever shown - completely silent regardless of
        // @mention/@think/mode override. This is the safest way to sit in
        // a group and just watch.
        if (observerMode) {
            try {
                await axios.post(`${WEBUI_API}/api/log-only`, {
                    message: msg.body,
                    chat_id: chatId,
                    sender_name: senderName,
                    is_group: isGroup,
                });
            } catch (e) { /* non-fatal */ }
            return;
        }

        let shouldReply = false;
        let wasMentioned = false;
        let triggerReason = '';

        if (isGroup) {
            // Pull the live setting from the panel on every message, so a
            // toggle flip takes effect immediately without restarting the
            // bridge.
            let requireMention = true;
            try {
                const settingsRes = await axios.get(`${WEBUI_API}/api/settings`);
                requireMention = settingsRes.data.require_mention_in_groups !== false;
            } catch (e) { /* fail safe to "required" if panel unreachable */ }

            const botId = client.info.wid._serialized;
            const mentioned = !!(msg.mentionedIds && msg.mentionedIds.includes(botId));
            const hasThinkTag = /@think\b/i.test(msg.body || '');

            // "Replied to bot" - someone tapped reply on one of the bot's
            // own previous messages. Counts as addressing it directly even
            // with no @mention.
            let repliedToBot = false;
            if (msg.hasQuotedMsg) {
                try {
                    const quoted = await msg.getQuotedMessage();
                    repliedToBot = !!(quoted && quoted.fromMe);
                } catch (e) { /* ignore - treat as not a reply-to-bot */ }
            }

            if (!requireMention) {
                // Open-mic mode: bot replies to every message in this group.
                shouldReply = true;
                triggerReason = 'open-mic (mention not required)';
            } else if (mentioned || hasThinkTag || repliedToBot) {
                shouldReply = true;
                wasMentioned = mentioned;
                triggerReason = mentioned ? 'mentioned' : hasThinkTag ? '@think tag' : 'replied to bot';
            }

            if (shouldReply) {
                await sendLogToUI(`[BRIDGE] Replying in group "${chat.name}" (${triggerReason}, from ${senderName})`);
            }

            // Regardless of whether we're replying, log every group message
            // to that group's memory/transcript so the bot has real context
            // of the conversation whenever it does speak. This is a
            // log-only call - it never triggers a reply by itself.
            try {
                await axios.post(`${WEBUI_API}/api/log-only`, {
                    message: msg.body,
                    chat_id: chatId,
                    sender_name: senderName,
                    is_group: true,
                });
            } catch (e) { /* non-fatal - context logging is best-effort */ }

        } else {
            // DM Logic: reply to everything (subject to block list, already checked above)
            shouldReply = true;
        }

        if (!shouldReply) return;

        // Show typing indicator immediately so there's no dead air while
        // we wait on the LLM call itself.
        await chat.sendStateTyping();

        const response = await axios.post(`${WEBUI_API}/api/chat`, {
            message: msg.body,
            chat_id: chatId,
            sender_name: senderName,
            is_group: isGroup,
            was_mentioned: wasMentioned,
        });

        const parts = response.data.parts || [];
        if (parts.length === 0) return; // bot disabled / blocked / nothing to say

        // Send each part with its own typing pause - this is what makes it
        // feel human instead of an instant wall-of-text dump.
        for (const part of parts) {
            await chat.sendStateTyping();
            await sleep(part.delay_ms || 800);
            await msg.reply(part.text);
        }

    } catch (err) {
        await sendLogToUI(`<span class='text-red-500'>[ERROR] Pipeline failure: ${err.message}</span>`);
    }
});

// Boot the client with a catch loop
client.initialize().catch(err => {
    console.error("=> Failed to initialize WhatsApp Client:", err);
    sendLogToUI(`<span class='text-red-500'>[FATAL] Failed to boot Chrome instance. Delete .wwebjs_auth folder and restart.</span>`);
});
