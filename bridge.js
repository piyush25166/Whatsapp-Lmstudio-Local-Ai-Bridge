const { Client, LocalAuth } = require('whatsapp-web.js');
const axios = require('axios');

// ==========================================
// 🛡️ ANTI-CRASH PROTOCOLS
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

client.on('qr', async (qr) => { 
    console.log("=> QR Code captured. Broadcasting to UI...");
    try { await axios.post(`${WEBUI_API}/api/update-qr`, { qr }); } catch (e) {}
});

client.on('ready', async () => {
    try {
        await axios.post(`${WEBUI_API}/api/update-status`, { status: 'Connected' });
        await sendLogToUI("<span class='text-green-400'>[BRIDGE] Architecture meshed with WhatsApp Web servers.</span>");
    } catch (e) {}
});

client.on('message', async msg => {
    // Ignore self-messages and non-text media
    if (msg.fromMe || msg.type !== 'chat') return;

    try {
        const chat = await msg.getChat();
        const contact = await msg.getContact();
        const senderName = contact.pushname || contact.name || contact.number;
        
        let shouldProcess = false;

        // Group Logic: Must be explicitly @mentioned
        if (chat.isGroup) {
            const botId = client.info.wid._serialized;
            if (msg.mentionedIds && msg.mentionedIds.includes(botId)) {
                shouldProcess = true;
                await sendLogToUI(`[BRIDGE] Waking up for @mention in group from ${senderName}`);
            }
        } 
        // DM Logic: Reply to everything
        else {
            shouldProcess = true;
        }

        if (shouldProcess) {
            // 🔥 NATIVE TYPING INDICATOR
            await chat.sendStateTyping(); 
            
            // Route to Python Backend
            const response = await axios.post(`${WEBUI_API}/api/chat`, {
                message: msg.body,
                chat_id: msg.from, // Used for isolated memory
                sender_name: senderName, 
                is_group: chat.isGroup
            });
            
            // Send Reply (Typing indicator stops automatically)
            await msg.reply(response.data.reply);
        }
    } catch (err) {
        await sendLogToUI(`<span class='text-red-500'>[❌ BRIDGE ERROR] Pipeline failure: ${err.message}</span>`);
    }
});

// Boot the client with a catch loop
client.initialize().catch(err => {
    console.error("=> Failed to initialize WhatsApp Client:", err);
    sendLogToUI(`<span class='text-red-500'>[FATAL] Failed to boot Chrome instance. Delete .wwebjs_auth folder and restart.</span>`);
});