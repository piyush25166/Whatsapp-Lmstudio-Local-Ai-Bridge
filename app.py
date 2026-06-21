import os
import requests
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# Shared application state
bot_state = {
    "whatsapp_status": "Disconnected",
    "qr_data": "",
    "logs": [],
    "lm_studio_connected": False,
    "available_models": [],
    "selected_model": "local-model",  # Default fallback
}

LM_STUDIO_URL = "http://127.0.0.1:1234"


def add_log(text):
    bot_state["logs"].append(text)
    if len(bot_state["logs"]) > 50:
        bot_state["logs"].pop(0)


@app.route("/")
def index():
    # Sync available models from LM Studio
    try:
        response = requests.get(f"{LM_STUDIO_URL}/v1/models", timeout=2)
        if response.status_code == 200:
            models_data = response.json()
            bot_state["available_models"] = [
                m["id"] for m in models_data.get("data", [])
            ]
            bot_state["lm_studio_connected"] = True
            if (
                bot_state["selected_model"] == "local-model"
                and bot_state["available_models"]
            ):
                bot_state["selected_model"] = bot_state["available_models"][0]
        else:
            bot_state["lm_studio_connected"] = False
    except Exception:
        bot_state["lm_studio_connected"] = False

    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI WhatsApp Bot Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/qrcode@1.4.4/build/qrcode.min.js"></script>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }
            .card { background: #1e1e1e; border: 1px solid #333; padding: 20px; border-radius: 8px; }
            h1, h2, h3 { margin-top: 0; color: #fff; }
            .status { font-weight: bold; padding: 4px 10px; border-radius: 4px; display: inline-block; font-size: 0.9em; }
            .connected { background: #1b5e20; color: #4caf50; }
            .disconnected { background: #b71c1c; color: #f44336; }
            .waiting { background: #e65100; color: #ff9800; }
            #qrcode { background: white; padding: 15px; width: 200px; height: 200px; margin: 15px auto; border-radius: 4px; display: none; }
            .qr-box { text-align: center; background: #252525; padding: 15px; border-radius: 6px; margin-top: 10px; }
            .log-box { background: #000; font-family: monospace; height: 300px; overflow-y: auto; padding: 12px; border-radius: 4px; border: 1px solid #333; color: #00ff00; font-size: 0.9em; line-height: 1.5; }
            select { width: 100%; padding: 10px; background: #2a2a2a; color: #fff; border: 1px solid #444; border-radius: 4px; font-size: 1em; margin-top: 10px; cursor: pointer; }
            select:focus { border-color: #00e5ff; outline: none; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 AI WhatsApp Bot Control Center</h1>
            <p>Unified pipeline management interface running on local hardware protocols.</p>
            
            <div class="grid">
                <div class="card">
                    <h2>WhatsApp Core Link</h2>
                    <p>Status: <span id="status-badge" class="status disconnected">Checking Link...</span></p>
                    <div class="qr-box">
                        <p id="qr-text">Initializing session tokens...</p>
                        <canvas id="qrcode"></canvas>
                    </div>
                </div>

                <div class="card">
                    <h2>LM Studio Core</h2>
                    <p>Endpoint Status: <span id="lm-status" class="status disconnected">Checking Endpoint...</span></p>
                    <h3 style="margin-top:20px;">Select Active Model Target</h3>
                    <select id="model-select" onchange="changeModel(this.value)">
                        <option>Loading models...</option>
                    </select>
                </div>
            </div>

            <div class="card" style="margin-top: 20px;">
                <h2>Live Execution Logs</h2>
                <div id="log-box" class="log-box"></div>
            </div>
        </div>

        <script>
            let currentSelectedModel = "";

            async function changeModel(modelName) {
                await fetch('/api/select-model', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ model: modelName })
                });
            }

            async function pollState() {
                try {
                    const res = await fetch('/api/status');
                    const data = await res.json();
                    
                    // Sync Link State
                    const badge = document.getElementById('status-badge');
                    badge.innerText = data.whatsapp_status;
                    badge.className = 'status ' + data.whatsapp_status.toLowerCase();
                    
                    // Render QR Components
                    const canvas = document.getElementById('qrcode');
                    const qrText = document.getElementById('qr-text');
                    if (data.whatsapp_status === 'Waiting' && data.qr_data) {
                        qrText.innerText = "Scan this token configuration with your WhatsApp app:";
                        canvas.style.display = 'block';
                        QRCode.toCanvas(canvas, data.qr_data, { width: 200 });
                    } else if (data.whatsapp_status === 'Connected') {
                        qrText.innerText = "🔒 Session authenticated and operational.";
                        canvas.style.display = 'none';
                    } else {
                        canvas.style.display = 'none';
                    }

                    // Sync LM Studio State & Dropdown
                    const lmBadge = document.getElementById('lm-status');
                    const select = document.getElementById('model-select');
                    
                    if (data.lm_studio_connected) {
                        lmBadge.innerText = "Active (Port 1234)";
                        lmBadge.className = "status connected";
                        
                        if (data.available_models.length > 0) {
                            if (currentSelectedModel !== data.selected_model || select.options.length <= 1) {
                                currentSelectedModel = data.selected_model;
                                select.innerHTML = data.available_models.map(m => 
                                    `<option value="${m}" ${m === data.selected_model ? 'selected' : ''}>🎯 ${m}</option>`
                                ).join('');
                            }
                        } else {
                            select.innerHTML = "<option>⚠️ No models loaded in LM Studio</option>";
                        }
                    } else {
                        lmBadge.innerText = "Offline";
                        lmBadge.className = "status disconnected";
                        select.innerHTML = "<option>Start LM Studio server instance</option>";
                    }

                    // Flush System Streams
                    const logBox = document.getElementById('log-box');
                    logBox.innerHTML = data.logs.map(log => `<div>${log}</div>`).join('');
                    logBox.scrollTop = logBox.scrollHeight;

                } catch (e) { console.error("Poll breakdown:", e); }
            }
            setInterval(pollState, 1500);
            pollState();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(bot_state)


@app.route("/api/select-model", methods=["POST"])
def select_model():
    bot_state["selected_model"] = request.json.get("model", "local-model")
    add_log(
        f"[SYSTEM] Switched targeted model execution context to: {bot_state['selected_model']}"
    )
    return jsonify({"status": "updated"})


@app.route("/api/bridge-log", methods=["POST"])
def bridge_log():
    text = request.json.get("log", "")
    add_log(text)
    return jsonify({"status": "logged"})


@app.route("/api/update-status", methods=["POST"])
def update_status():
    status = request.json.get("status", "Disconnected")
    bot_state["whatsapp_status"] = status
    if status == "Connected":
        bot_state["qr_data"] = ""
    add_log(f"[SYSTEM] Channel link shifted to status: {status}")
    return jsonify({"status": "synced"})


@app.route("/api/update-qr", methods=["POST"])
def update_qr():
    bot_state["qr_data"] = request.json.get("qr", "")
    bot_state["whatsapp_status"] = "Waiting"
    add_log("[GATEWAY] Fresh WhatsApp authentication payload received.")
    return jsonify({"status": "synced"})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    sender = data.get("sender", "unknown")

    add_log(f"📩 Inbound text from [{sender}]: {user_message}")

    try:
        # Re-initialize OpenAI client dynamically with the user-selected model
        client = OpenAI(base_url=f"{LM_STUDIO_URL}/v1", api_key="lm-studio")

        response = client.chat.completions.create(
            model=bot_state["selected_model"],
            messages=[
                {
                    "role": "system",
                    "content": "You are an automated local assistant replying concisely via WhatsApp.",
                },
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
        )
        ai_reply = response.choices[0].message.content
        add_log(
            f"🚀 Outbound response generated successfully via {bot_state['selected_model']}."
        )
        return jsonify({"reply": ai_reply})
    except Exception as e:
        add_log(f"❌ Processing Fault: {str(e)}")
        return jsonify(
            {
                "reply": "System optimization alert. Local inference server timed out or model mismatch."
            }
        ), 500


if __name__ == "__main__":
    app.run(port=5000, debug=True, use_reloader=False)
