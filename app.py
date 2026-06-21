import os
import requests
import threading
from flask import Flask, render_template_string, request, jsonify
from openai import OpenAI
from duckduckgo_search import DDGS

app = Flask(__name__)

LM_STUDIO_URL = "http://127.0.0.1:1234"

# ==========================================
# 🔒 LOCKED SYSTEM & PERSONALITY PROMPT
# ==========================================
SYSTEM_PROMPT = """You are a highly capable, brilliant, and automated AI assistant. 
Your personality is warm, engaging, insightful, and slightly witty. You do not act like a robotic machine; you are confident and conversational.
You possess a vast intellect and provide incredibly accurate, straightforward answers. 
If someone mentions other people or you are in a group chat, acknowledge the context naturally. 
Format your responses beautifully for WhatsApp (using *bold* for emphasis, and bullet points where helpful)."""

# Application State
bot_state = {
    "whatsapp_status": "Disconnected",
    "qr_data": "",
    "logs": [],
    "lm_studio_connected": False,
    "available_models": [],
    "selected_model": "local-model",
    "internet_enabled": False,
}

# Advanced Memory Dictionary
chat_memory = {}
MEMORY_LIMIT_CHARS = 6000


def add_log(text):
    bot_state["logs"].append(text)
    if len(bot_state["logs"]) > 100:
        bot_state["logs"].pop(0)


def summarize_memory(chat_id, model_name):
    """Background thread function to compress memory without lagging the live chat."""
    mem = chat_memory[chat_id]
    conversation_text = "\n".join(
        [f"{m['role']}: {m['content']}" for m in mem["messages"]]
    )
    prompt = f"Summarize the following conversation in under 1000 characters. Keep key facts, user names, and the general context intact.\n\n{conversation_text}"

    try:
        client = OpenAI(base_url=f"{LM_STUDIO_URL}/v1", api_key="lm-studio")
        res = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        mem["summary"] = res.choices[0].message.content
        mem["messages"] = []  # Wipe the raw bloat
        mem["char_count"] = 0
        add_log(f"[🧠 MEMORY] Context successfully compressed for chat: {chat_id}")
    except Exception as e:
        add_log(f"[❌ MEMORY ERROR] Summarization failed: {str(e)}")


@app.route("/")
def index():
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
    except:
        bot_state["lm_studio_connected"] = False

    # 🚀 MODERN TAILWIND CSS DASHBOARD
    html_template = """
    <!DOCTYPE html>
    <html lang="en" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NEXUS | Agent Control Center</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/qrcode@1.4.4/build/qrcode.min.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;700&display=swap');
            body { font-family: 'Inter', sans-serif; background-color: #050505; color: #e5e5e5; }
            .glass-panel { background: rgba(20, 20, 25, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; }
            .log-terminal { font-family: 'JetBrains Mono', monospace; background: #000000; border: 1px solid #222; color: #00ff66; box-shadow: inset 0 0 20px rgba(0, 255, 100, 0.05); }
            .status-badge { transition: all 0.3s ease; }
            ::-webkit-scrollbar { width: 8px; }
            ::-webkit-scrollbar-track { background: #111; }
            ::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
        </style>
    </head>
    <body class="min-h-screen p-4 md:p-8">
        <div class="max-w-6xl mx-auto space-y-6">
            
            <!-- Header -->
            <div class="flex items-center justify-between glass-panel p-6">
                <div>
                    <h1 class="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
                        <span class="text-indigo-500">⚡</span> NEXUS Command Core
                    </h1>
                    <p class="text-gray-400 text-sm mt-1">Autonomous WhatsApp Pipeline & Context Manager</p>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <!-- WhatsApp Node -->
                <div class="glass-panel p-6 flex flex-col">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-xl font-semibold text-white">📱 Comms Node</h2>
                        <span id="status-badge" class="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-red-900/50 text-red-400 border border-red-500/20 status-badge">Disconnected</span>
                    </div>
                    
                    <div class="flex-grow flex flex-col items-center justify-center bg-black/40 rounded-xl p-6 border border-white/5">
                        <div id="qr-container" class="hidden flex-col items-center">
                            <p class="text-sm text-gray-400 mb-4 text-center">Scan QR code to inject bridge payload</p>
                            <div class="p-3 bg-white rounded-lg shadow-2xl">
                                <canvas id="qrcode"></canvas>
                            </div>
                        </div>
                        <div id="connected-state" class="text-center">
                            <div class="w-16 h-16 bg-green-500/10 rounded-full flex items-center justify-center mx-auto mb-4 border border-green-500/20">
                                <span class="text-2xl">🔒</span>
                            </div>
                            <p class="text-green-400 font-medium">Session Authenticated</p>
                            <p class="text-xs text-gray-500 mt-1">Listening for inbound traffic...</p>
                        </div>
                    </div>
                </div>

                <!-- AI Engine Node -->
                <div class="glass-panel p-6 flex flex-col">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-xl font-semibold text-white">🧠 Inference Core</h2>
                        <span id="lm-status" class="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-red-900/50 text-red-400 border border-red-500/20 status-badge">Offline</span>
                    </div>

                    <div class="space-y-5">
                        <div>
                            <label class="block text-sm font-medium text-gray-400 mb-2">Active Language Model Context</label>
                            <select id="model-select" onchange="changeModel(this.value)" class="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-indigo-500 appearance-none cursor-pointer">
                                <option>Awaiting Engine Boot...</option>
                            </select>
                        </div>

                        <div class="pt-4 border-t border-white/10">
                            <label class="block text-sm font-medium text-gray-400 mb-3">Capabilities</label>
                            <button id="net-toggle" onclick="toggleNet()" class="w-full relative overflow-hidden group bg-gray-800 hover:bg-gray-700 border border-gray-600 text-white font-medium py-3 px-4 rounded-lg transition-all duration-200 flex items-center justify-between">
                                <span class="flex items-center gap-2">
                                    <span id="net-icon">🌐</span> Live Web Search
                                </span>
                                <span id="net-status-text" class="text-xs font-bold uppercase text-gray-400">Disabled</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Global Terminal -->
            <div class="glass-panel p-6">
                <div class="flex items-center gap-2 mb-4">
                    <span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                    <h2 class="text-sm font-semibold text-gray-300 uppercase tracking-widest">Live Execution Telemetry</h2>
                </div>
                <div id="log-box" class="log-terminal h-80 overflow-y-auto p-4 text-sm leading-relaxed rounded-xl"></div>
            </div>
            
        </div>

        <script>
            let currentSelectedModel = "";
            let netState = false;

            async function changeModel(modelName) {
                await fetch('/api/select-model', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ model: modelName }) });
            }

            async function toggleNet() {
                const res = await fetch('/api/toggle-internet', { method: 'POST' });
                const data = await res.json();
                updateNetUI(data.state);
            }

            function updateNetUI(state) {
                netState = state;
                const btn = document.getElementById('net-toggle');
                const statusText = document.getElementById('net-status-text');
                if(state) {
                    btn.classList.replace('bg-gray-800', 'bg-indigo-900/40');
                    btn.classList.replace('border-gray-600', 'border-indigo-500/50');
                    statusText.innerText = "Enabled";
                    statusText.className = "text-xs font-bold uppercase text-indigo-400";
                } else {
                    btn.classList.replace('bg-indigo-900/40', 'bg-gray-800');
                    btn.classList.replace('border-indigo-500/50', 'border-gray-600');
                    statusText.innerText = "Disabled";
                    statusText.className = "text-xs font-bold uppercase text-gray-400";
                }
            }

            async function pollState() {
                try {
                    const res = await fetch('/api/status');
                    const data = await res.json();
                    
                    // Comms Node UI
                    const badge = document.getElementById('status-badge');
                    const qrContainer = document.getElementById('qr-container');
                    const connectedState = document.getElementById('connected-state');
                    const canvas = document.getElementById('qrcode');
                    
                    badge.innerText = data.whatsapp_status;
                    if(data.whatsapp_status === 'Connected') {
                        badge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-green-900/40 text-green-400 border border-green-500/30 status-badge';
                        qrContainer.classList.add('hidden');
                        connectedState.classList.remove('hidden');
                    } else if (data.whatsapp_status === 'Waiting') {
                        badge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-orange-900/40 text-orange-400 border border-orange-500/30 status-badge';
                        connectedState.classList.add('hidden');
                        qrContainer.classList.remove('hidden');
                        if(data.qr_data) QRCode.toCanvas(canvas, data.qr_data, { width: 220, margin: 1, color: { dark: '#000000', light: '#ffffff' } });
                    } else {
                        badge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-red-900/40 text-red-400 border border-red-500/30 status-badge';
                        qrContainer.classList.add('hidden');
                        connectedState.classList.remove('hidden');
                        connectedState.innerHTML = '<span class="text-4xl animate-bounce block">⚠️</span><p class="text-red-400 font-medium mt-2">Bridge Offline</p><p class="text-xs text-gray-500">Run `node bridge.js`</p>';
                    }

                    // Inference Node UI
                    const lmBadge = document.getElementById('lm-status');
                    const select = document.getElementById('model-select');
                    if (data.lm_studio_connected) {
                        lmBadge.innerText = "Port 1234 Active"; 
                        lmBadge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-green-900/40 text-green-400 border border-green-500/30 status-badge';
                        if (currentSelectedModel !== data.selected_model || select.options.length <= 1) {
                            currentSelectedModel = data.selected_model;
                            select.innerHTML = data.available_models.map(m => `<option value="${m}" ${m === data.selected_model ? 'selected' : ''}>🎯 ${m}</option>`).join('');
                        }
                    } else {
                        lmBadge.innerText = "Offline"; 
                        lmBadge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-red-900/40 text-red-400 border border-red-500/30 status-badge';
                        select.innerHTML = '<option>Start LM Studio local server...</option>';
                    }

                    if(netState !== data.internet_enabled) updateNetUI(data.internet_enabled);

                    // Telemetry UI
                    const logBox = document.getElementById('log-box');
                    // Only update and scroll if logs changed to prevent scroll jumping
                    const currentLogHTML = data.logs.map(log => `<div class="mb-1 border-b border-white/5 pb-1"><span class="text-gray-600 mr-2">></span>${log}</div>`).join('');
                    if(logBox.innerHTML !== currentLogHTML) {
                        logBox.innerHTML = currentLogHTML;
                        logBox.scrollTop = logBox.scrollHeight;
                    }
                } catch (e) {}
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
    add_log(f"[SYSTEM] Linked to model context: {bot_state['selected_model']}")
    return jsonify({"status": "updated"})


@app.route("/api/toggle-internet", methods=["POST"])
def toggle_internet():
    bot_state["internet_enabled"] = not bot_state["internet_enabled"]
    add_log(f"[SYSTEM] Live Web Search set to: {bot_state['internet_enabled']}")
    return jsonify({"state": bot_state["internet_enabled"]})


@app.route("/api/bridge-log", methods=["POST"])
def bridge_log():
    add_log(request.json.get("log", ""))
    return jsonify({"status": "logged"})


@app.route("/api/update-status", methods=["POST"])
def update_status():
    status = request.json.get("status", "Disconnected")
    bot_state["whatsapp_status"] = status
    if status == "Connected":
        bot_state["qr_data"] = ""
    return jsonify({"status": "synced"})


@app.route("/api/update-qr", methods=["POST"])
def update_qr():
    bot_state["qr_data"] = request.json.get("qr", "")
    bot_state["whatsapp_status"] = "Waiting"
    return jsonify({"status": "synced"})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    chat_id = data.get("chat_id", "unknown")
    sender_name = data.get("sender_name", "User")
    is_group = data.get("is_group", False)

    add_log(f"📩 [{sender_name} {'in Group' if is_group else 'DM'}]: {user_message}")

    if chat_id not in chat_memory:
        chat_memory[chat_id] = {"summary": "", "messages": [], "char_count": 0}
    mem = chat_memory[chat_id]

    formatted_user_msg = f"[{sender_name}]: {user_message}"

    # ⚡ TOKEN-OPTIMIZED WEB SEARCH
    search_context = ""
    if bot_state["internet_enabled"]:
        try:
            add_log(
                "<span class='text-blue-400'>[🌐 SCRAPER] Fetching highly-trimmed live facts...</span>"
            )
            results = DDGS().text(keywords=user_message, max_results=2)
            if results:
                trimmed_facts = []
                for r in results:
                    title = r.get("title", "Fact")
                    body = r.get("body", "")
                    # Trim aggressively to save tokens
                    short_body = body[:200] + "..." if len(body) > 200 else body
                    trimmed_facts.append(f"- {title}: {short_body}")
                search_context = "\n\n[MINIFIED WEB DATA]:\n" + "\n".join(trimmed_facts)
        except Exception as e:
            add_log(
                f"<span class='text-yellow-400'>⚠️ Web search bypassed: {str(e)}</span>"
            )

    # Construct Payload
    payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    if mem["summary"]:
        payload.append(
            {
                "role": "system",
                "content": f"Prior Conversation Memory Summary:\n{mem['summary']}",
            }
        )
    for msg in mem["messages"]:
        payload.append(msg)

    # Inject user msg + context (Never saved to history to prevent token explosion)
    payload.append({"role": "user", "content": formatted_user_msg + search_context})

    try:
        client = OpenAI(base_url=f"{LM_STUDIO_URL}/v1", api_key="lm-studio")
        response = client.chat.completions.create(
            model=bot_state["selected_model"], messages=payload, temperature=0.7
        )
        ai_reply = response.choices[0].message.content
        add_log(f"<span class='text-purple-400'>🚀 Outbound response generated.</span>")

        # Save to memory
        mem["messages"].append({"role": "user", "content": formatted_user_msg})
        mem["messages"].append({"role": "assistant", "content": ai_reply})
        mem["char_count"] += len(formatted_user_msg) + len(ai_reply)

        if mem["char_count"] > MEMORY_LIMIT_CHARS:
            threading.Thread(
                target=summarize_memory, args=(chat_id, bot_state["selected_model"])
            ).start()

        return jsonify({"reply": ai_reply})
    except Exception as e:
        add_log(
            f"<span class='text-red-500'>❌ LM Studio Timeout/Error: {str(e)}</span>"
        )
        return jsonify(
            {
                "reply": "System architecture overwhelmed. Ensure LM Studio server is running."
            }
        ), 500


if __name__ == "__main__":
    app.run(port=5000, debug=True, use_reloader=False)
