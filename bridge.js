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

        let shouldProcess = false;
        let wasMentioned = false;

        // Group Logic: must be @mentioned OR contain the @think tag
        if (isGroup) {
            const botId = client.info.wid._serialized;
            const mentioned = msg.mentionedIds && msg.mentionedIds.includes(botId);
            const hasThinkTag = /@think\b/i.test(msg.body || '');
            if (mentioned || hasThinkTag) {
                shouldProcess = true;
                wasMentioned = mentioned;
                await sendLogToUI(`[BRIDGE] Waking up in group "${chat.name}" (from ${senderName})`);
            }
        }
        // DM Logic: reply to everything (subject to block list, checked below)
        else {
            shouldProcess = true;
        }

        if (!shouldProcess) return;

        // Contact gate - block list, also registers/updates this contact
        // in the admin panel's contact list even if it's the first message.
        let blocked = false;
        try {
            const gateRes = await axios.post(`${WEBUI_API}/api/check-contact`, {
                chat_id: chatId,
                display_name: displayName,
                is_group: isGroup,
            });
            blocked = gateRes.data.blocked;
        } catch (e) { /* fail open if panel unreachable */ }

        if (blocked) {
            await sendLogToUI(`[BRIDGE] Ignored message from blocked contact: ${displayName}`);
            return;
        }

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
