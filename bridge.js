const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');

// Initialize the WhatsApp Client
// LocalAuth saves your session so you only scan the QR code once
const client = new Client({
    authStrategy: new LocalAuth()
});

client.on('qr', (qr) => {
    // Generate and print the QR code to your terminal
    qrcode.generate(qr, { small: true });
    console.log('Scan the QR code above with your WhatsApp app to connect.');
});

client.on('ready', () => {
    console.log('Client is ready! WhatsApp connected and listening for messages...');
});

client.on('message', async msg => {
    // Filter to only respond to text messages from individuals (ignore groups/status updates)
    if (msg.from.includes('@c.us') && msg.type === 'chat') {
        console.log(`Received from ${msg.from}: ${msg.body}`);
        
        try {
            // Forward the WhatsApp message to your Python Flask server
            const response = await axios.post('http://127.0.0.1:5000/chat', {
                message: msg.body,
                sender: msg.from
            });
            
            // Send the Python/LM Studio reply back to the WhatsApp user
            const aiReply = response.data.reply;
            msg.reply(aiReply);
            
        } catch (err) {
            console.error("Error communicating with Python backend:", err.message);
        }
    }
});

client.initialize();