const { Client, LocalAuth } = require('whatsapp-web.js');
const axios = require('axios');

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        handleSIGINT: false,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

const WEBUI_API = 'http://127.0.0.1:5000';

async function sendLogToUI(message) {
    try {
        await axios.post(`${WEBUI_API}/api/bridge-log`, { log: message });
    } catch (e) {
        console.log("Failed to send log to UI:", e.message);
    }
}

client.on('qr', async (qr) => {
    try {
        await axios.post(`${WEBUI_API}/api/update-qr`, { qr });
    } catch (err) {
        console.error('Failed to broadcast pairing state down to Flask:', err.message);
    }
});

client.on('ready', async () => {
    try {
        await axios.post(`${WEBUI_API}/api/update-status`, { status: 'Connected' });
        await sendLogToUI("[BRIDGE] Core engine fully synchronized with WhatsApp Web cluster.");
    } catch (err) {
        console.error('State synchronization fault:', err.message);
    }
});

// Capture pristine incoming messages from external accounts cleanly
client.on('message', async msg => {
    // Ignore group chats entirely to conserve local hardware resources
    if (msg.from.includes('@g.us')) return;

    await sendLogToUI(`[BRIDGE] Intercepted incoming transmission type [${msg.type}] from [${msg.from}]`);

    // Only process standard text conversations
    if (msg.type === 'chat') {
        try {
            // 1. Fetch the active chat instance
            const chat = await msg.getChat();
            
            // 2. Broadcast the native "typing..." presence to the sender
            await chat.sendStateTyping();
            await sendLogToUI(`[BRIDGE] Triggered native "typing..." status flag for chat thread.`);

            // 3. Pipe the text to your Flask app / LM Studio backend
            const response = await axios.post(`${WEBUI_API}/api/chat`, {
                message: msg.body,
                sender: msg.from
            });
            
            // 4. Dispatch response (this automatically concludes the typing animation)
            await msg.reply(response.data.reply);
            await sendLogToUI(`[BRIDGE] Outbound reply dispatched smoothly to user.`);
        } catch (err) {
            await sendLogToUI(`[❌ BRIDGE ERROR] Data pipeline delivery breakdown: ${err.message}`);
        }
    } else {
        await sendLogToUI(`[BRIDGE] Ignored message type: ${msg.type}. System only responds to plain text.`);
    }
});

client.initialize();