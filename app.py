import os
import requests
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from skills import NexusSkills
from memory_manager import MemoryManager

app = Flask(__name__, template_folder="templates")

LM_STUDIO_URL = "http://127.0.0.1:1234"
memory_engine = MemoryManager()

# Global App State
state = {
    "whatsapp_status": "Disconnected",
    "qr_data": "",
    "logs": [],
    "lm_studio_connected": False,
    "available_models": [],
    "selected_model": "local-model",
    "internet_enabled": False,
    "total_messages_processed": 0,
}


def log(text):
    state["logs"].append(text)
    if len(state["logs"]) > 100:
        state["logs"].pop(0)


def load_prompts():
    prompt = ""
    if os.path.exists("character.md"):
        with open("character.md", "r", encoding="utf-8") as f:
            prompt += f.read() + "\n\n"
    if os.path.exists("skill.md"):
        with open("skill.md", "r", encoding="utf-8") as f:
            prompt += f.read()
    return prompt if prompt else "You are NEXUS, a highly advanced local AI."


# --- UI ROUTES ---
@app.route("/")
def index():
    return render_template("index.html")


# --- DATA ENDPOINTS ---
@app.route("/api/state", methods=["GET"])
def get_state():
    try:
        res = requests.get(f"{LM_STUDIO_URL}/v1/models", timeout=2)
        if res.status_code == 200:
            state["available_models"] = [m["id"] for m in res.json().get("data", [])]
            state["lm_studio_connected"] = True
            if state["selected_model"] == "local-model" and state["available_models"]:
                state["selected_model"] = state["available_models"][0]
        else:
            state["lm_studio_connected"] = False
    except:
        state["lm_studio_connected"] = False

    return jsonify({**state, "active_chats": len(memory_engine.get_all_memories())})


@app.route("/api/memories", methods=["GET"])
def get_memories():
    return jsonify(memory_engine.get_all_memories())


@app.route("/api/clear-memory", methods=["POST"])
def clear_memory():
    chat_id = request.json.get("id")
    success = memory_engine.wipe_memory(chat_id)
    if success:
        log(f"🗑️ Wiped memory banks for: {chat_id}")
    return jsonify({"success": success})


@app.route("/api/toggle-internet", methods=["POST"])
def toggle_internet():
    state["internet_enabled"] = not state["internet_enabled"]
    log(f"🌐 Internet scraping toggled: {state['internet_enabled']}")
    return jsonify({"state": state["internet_enabled"]})


@app.route("/api/select-model", methods=["POST"])
def select_model():
    state["selected_model"] = request.json.get("model", "local-model")
    log(f"🧠 Inference core switched to: {state['selected_model']}")
    return jsonify({"success": True})


# --- BRIDGE ENDPOINTS ---
@app.route("/api/bridge-log", methods=["POST"])
def bridge_log():
    log(request.json.get("log", ""))
    return jsonify({"status": "logged"})


@app.route("/api/update-status", methods=["POST"])
def update_status():
    status = request.json.get("status", "Disconnected")
    state["whatsapp_status"] = status
    if status == "Connected":
        state["qr_data"] = ""
    return jsonify({"status": "synced"})


@app.route("/api/update-qr", methods=["POST"])
def update_qr():
    state["qr_data"] = request.json.get("qr", "")
    state["whatsapp_status"] = "Waiting"
    return jsonify({"status": "synced"})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_msg = data.get("message", "")
    chat_id = data.get("chat_id", "unknown")
    sender = data.get("sender_name", "User")

    state["total_messages_processed"] += 1
    log(f"📩 [{sender}]: {user_msg}")

    mem = memory_engine.load_memory(chat_id)
    formatted_msg = f"[{sender}]: {user_msg}"

    # Internet Injection via Skills Module
    search_context = ""
    if state["internet_enabled"]:
        log("🌐 Fetching real-time web context...")
        search_context = NexusSkills.fetch_web_context(user_msg)

    # Payload Construction
    payload = [{"role": "system", "content": load_prompts()}]
    if mem["summary"]:
        payload.append(
            {"role": "system", "content": f"Prior Context:\n{mem['summary']}"}
        )
    for m in mem["messages"]:
        payload.append(m)
    payload.append({"role": "user", "content": formatted_msg + search_context})

    try:
        client = OpenAI(base_url=f"{LM_STUDIO_URL}/v1", api_key="lm-studio")
        response = client.chat.completions.create(
            model=state["selected_model"], messages=payload, temperature=0.7
        )
        reply = response.choices[0].message.content
        log("🚀 Outbound response generated successfully.")

        # Save state
        mem["messages"].append({"role": "user", "content": formatted_msg})
        mem["messages"].append({"role": "assistant", "content": reply})
        mem["char_count"] += len(formatted_msg) + len(reply)
        memory_engine.save_memory(mem)

        # Trigger Summarizer if overgrown
        if mem["char_count"] > memory_engine.char_limit:
            memory_engine.trigger_summarize(
                chat_id, LM_STUDIO_URL, state["selected_model"], log
            )

        return jsonify({"reply": reply})
    except Exception as e:
        log(f"❌ AI Core Error: {str(e)}")
        return jsonify({"reply": "System optimization alert. Core offline."}), 500


if __name__ == "__main__":
    app.run(port=5000, debug=True, use_reloader=False)
