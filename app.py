import os
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify
from openai import OpenAI

from skills import NexusSkills
from memory_manager import MemoryManager
from contact_manager import ContactManager
from settings_manager import SettingsManager
from prompt_manager import PromptManager
from humanizer import humanize_reply

app = Flask(__name__, template_folder="templates")

LM_STUDIO_URL = "http://127.0.0.1:1234"

memory_engine = MemoryManager()
contacts = ContactManager()
settings = SettingsManager()
prompts = PromptManager()
memory_engine.char_limit = settings.get("memory_char_limit", 6000)

# Global App State - runtime/connection info only. Anything the admin can
# configure persistently lives in settings.json via SettingsManager instead.
state = {
    "whatsapp_status": "Disconnected",
    "qr_data": "",
    "logs": [],
    "lm_studio_connected": False,
    "available_models": [],
    "total_messages_processed": 0,
}


def log(text):
    ts = datetime.now().strftime("%H:%M:%S")
    state["logs"].append(f"[{ts}] {text}")
    if len(state["logs"]) > 200:
        state["logs"].pop(0)


def load_default_persona_from_disk():
    """Reads character.md + skill.md as they exist on disk right now. Used
    both as the normal fallback AND as the source text the panel's editor
    pre-fills with the first time you open it."""
    prompt = ""
    if os.path.exists("character.md"):
        with open("character.md", "r", encoding="utf-8") as f:
            prompt += f.read() + "\n\n"
    if os.path.exists("skill.md"):
        with open("skill.md", "r", encoding="utf-8") as f:
            prompt += f.read()
    return prompt if prompt else "You are a helpful assistant."


def load_persona():
    """Builds the system prompt for this message.

    Precedence:
    1. If the admin has saved a live persona override from the panel, use
       that verbatim instead of character.md/skill.md.
    2. Otherwise fall back to character.md + skill.md from disk, exactly
       as before.
    Then, if global guidance text is set, it's appended as an additional
    instruction layered on top - this is the quick day-to-day steering box,
    separate from the full persona edit.
    """
    override = prompts.get_persona_override()
    base = override if override else load_default_persona_from_disk()

    guidance = prompts.get_global_guidance()
    if guidance:
        base += f"\n\n---\nADMIN GUIDANCE (follow this for all replies right now): {guidance}"

    return base


# --- MODE RESOLUTION ---

def resolve_mode(chat_id, message_text, is_group, was_mentioned):
    """
    Decides "casual" or "thinking" for this specific incoming message.

    Priority order:
    1. Per-contact admin override (forced casual/thinking for this chat) wins
       outright, no matter what's in the message text.
    2. Explicit @think tag in the message text switches this ONE message to
       thinking mode.
    3. Otherwise: casual. (Whether the bot replies AT ALL in a group is
       decided by the bridge before this function is ever called - that's
       the require_mention_in_groups setting, a separate concern from which
       mode a reply uses once we've decided to send one.)
    """
    override = contacts.get_mode_override(chat_id)
    if override in ("casual", "thinking"):
        return override

    tag = settings.get("thinking_trigger_tag", "@think")
    if tag and tag.lower() in (message_text or "").lower():
        return "thinking"

    return "casual"


def mode_config(mode):
    if mode == "thinking":
        return {
            "max_tokens": int(settings.get("thinking_max_tokens", 700)),
            "temperature": float(settings.get("thinking_temperature", 0.6)),
        }
    return {
        "max_tokens": int(settings.get("casual_max_tokens", 120)),
        "temperature": float(settings.get("casual_temperature", 0.8)),
    }


# --- UI ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")


# --- STATE / SETTINGS ENDPOINTS ---

@app.route("/api/state", methods=["GET"])
def get_state():
    try:
        res = requests.get(f"{LM_STUDIO_URL}/v1/models", timeout=2)
        if res.status_code == 200:
            state["available_models"] = [m["id"] for m in res.json().get("data", [])]
            state["lm_studio_connected"] = True
            sel = settings.get("selected_model")
            if sel == "local-model" and state["available_models"]:
                settings.update({"selected_model": state["available_models"][0]})
        else:
            state["lm_studio_connected"] = False
    except Exception:
        state["lm_studio_connected"] = False

    return jsonify({
        **state,
        "settings": settings.get_all(),
        "active_chats": len(memory_engine.get_all_memories()),
    })


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(settings.get_all())


@app.route("/api/settings", methods=["POST"])
def update_settings():
    updates = request.json or {}
    new_settings = settings.update(updates)
    if "memory_char_limit" in updates:
        memory_engine.char_limit = new_settings["memory_char_limit"]
    log(f"⚙️ Settings updated: {list(updates.keys())}")
    return jsonify(new_settings)


@app.route("/api/settings/reset", methods=["POST"])
def reset_settings():
    new_settings = settings.reset_to_defaults()
    memory_engine.char_limit = new_settings["memory_char_limit"]
    log("⚙️ Settings reset to defaults")
    return jsonify(new_settings)


@app.route("/api/toggle-internet", methods=["POST"])
def toggle_internet():
    new_val = not settings.get("internet_enabled", False)
    settings.update({"internet_enabled": new_val})
    log(f"🌐 Internet access toggled: {new_val}")
    return jsonify({"state": new_val})


@app.route("/api/toggle-bot", methods=["POST"])
def toggle_bot():
    """Master kill switch - bridge checks this and goes silent everywhere."""
    new_val = not settings.get("bot_enabled", True)
    settings.update({"bot_enabled": new_val})
    log(f"🔌 Bot master switch: {'ON' if new_val else 'OFF'}")
    return jsonify({"state": new_val})


@app.route("/api/select-model", methods=["POST"])
def select_model():
    model = (request.json or {}).get("model", "local-model")
    settings.update({"selected_model": model})
    log(f"🧠 Inference core switched to: {model}")
    return jsonify({"success": True})


# --- PERSONA / PROMPT MANAGEMENT ENDPOINTS ---

@app.route("/api/persona", methods=["GET"])
def get_persona():
    """Returns everything the Persona panel tab needs: the currently active
    text (override if set, else what's on disk), whether an override is
    active, and the global guidance text."""
    override = prompts.get_persona_override()
    return jsonify({
        "persona_text": override if override else load_default_persona_from_disk(),
        "is_override_active": override is not None,
        "global_guidance": prompts.get_global_guidance(),
        "disk_text": load_default_persona_from_disk(),
    })


@app.route("/api/persona", methods=["POST"])
def save_persona():
    """Saves a live persona override. Takes effect on the very next
    message - no restart, no file editing needed."""
    text = (request.json or {}).get("persona_text", "")
    prompts.set_persona_override(text)
    log(f"🎭 Persona override saved ({len(text)} chars)")
    return jsonify({"success": True})


@app.route("/api/persona/revert", methods=["POST"])
def revert_persona():
    """Clears the override and goes back to character.md + skill.md as
    they exist on disk - the safety net if a live edit breaks something."""
    prompts.revert_persona_to_disk()
    log("🎭 Persona reverted to character.md + skill.md on disk")
    return jsonify({"success": True, "persona_text": load_default_persona_from_disk()})


@app.route("/api/guidance", methods=["POST"])
def save_guidance():
    """Saves the quick day-to-day steering note layered on top of the full
    persona. Separate from the persona override so you can clear one
    without touching the other."""
    text = (request.json or {}).get("guidance", "")
    prompts.set_global_guidance(text)
    log(f"💡 Global guidance updated ({len(text)} chars)" if text else "💡 Global guidance cleared")
    return jsonify({"success": True})


# --- CONTACT / GROUP MANAGEMENT ENDPOINTS ---

@app.route("/api/contacts", methods=["GET"])
def list_contacts():
    return jsonify(contacts.get_all())


@app.route("/api/contacts/<chat_id>", methods=["GET"])
def get_contact(chat_id):
    rec = contacts.get(chat_id)
    if not rec:
        return jsonify({"error": "not found"}), 404
    return jsonify(rec)


@app.route("/api/contacts/<chat_id>/status", methods=["POST"])
def set_contact_status(chat_id):
    status = (request.json or {}).get("status")
    ok = contacts.set_status(chat_id, status)
    if ok:
        log(f"👤 {chat_id} set to {status}")
    return jsonify({"success": ok})


@app.route("/api/contacts/<chat_id>/mode", methods=["POST"])
def set_contact_mode(chat_id):
    mode = (request.json or {}).get("mode")
    if mode == "auto":
        mode = None
    ok = contacts.set_mode_override(chat_id, mode)
    if ok:
        log(f"👤 {chat_id} mode override set to {mode or 'auto'}")
    return jsonify({"success": ok})


@app.route("/api/contacts/<chat_id>/observer", methods=["POST"])
def set_contact_observer(chat_id):
    """Toggles observer/silent mode for one specific contact or group -
    logs everything, replies to nothing, no typing indicator, regardless
    of @mention/@think/mode override."""
    enabled = bool((request.json or {}).get("enabled", True))
    ok = contacts.set_observer_mode(chat_id, enabled)
    if ok:
        log(f"👁️ {chat_id} observer mode set to {enabled}")
    return jsonify({"success": ok})


@app.route("/api/contacts/<chat_id>/notes", methods=["POST"])
def set_contact_notes(chat_id):
    notes = (request.json or {}).get("notes", "")
    ok = contacts.set_notes(chat_id, notes)
    return jsonify({"success": ok})


@app.route("/api/contacts/<chat_id>", methods=["DELETE"])
def delete_contact(chat_id):
    ok = contacts.delete_contact(chat_id)
    if ok:
        log(f"🗑️ Contact record removed: {chat_id}")
    return jsonify({"success": ok})


# --- MEMORY / TRANSCRIPT ENDPOINTS ---

@app.route("/api/memories", methods=["GET"])
def get_memories():
    return jsonify(memory_engine.get_all_memories())


@app.route("/api/transcript/<chat_id>", methods=["GET"])
def get_transcript(chat_id):
    limit = request.args.get("limit", 200, type=int)
    return jsonify(memory_engine.get_transcript(chat_id, limit=limit))


@app.route("/api/clear-memory", methods=["POST"])
def clear_memory():
    chat_id = (request.json or {}).get("id")
    success = memory_engine.wipe_memory(chat_id)
    if success:
        log(f"🗑️ Wiped memory + transcript for: {chat_id}")
    return jsonify({"success": success})


@app.route("/api/log-only", methods=["POST"])
def log_only():
    """Records a group message the bot SAW but is not replying to (e.g.
    'require mention' is on and nobody addressed it). This keeps the bot's
    memory of the group conversation continuous, so when it DOES reply it
    has real context instead of only ever seeing the single triggering
    message. Never calls the LLM, never costs tokens, never sends anything."""
    data = request.json or {}
    chat_id = data.get("chat_id", "unknown")
    sender = data.get("sender_name", "User")
    text = data.get("message", "")
    is_group = bool(data.get("is_group", False))

    if not settings.get("log_unreplied_group_messages", True):
        return jsonify({"logged": False})
    if contacts.is_blocked(chat_id):
        return jsonify({"logged": False})

    mem = memory_engine.load_memory(chat_id)
    formatted_msg = f"[{sender}]: {text}"
    mem["messages"].append({"role": "user", "content": formatted_msg})
    mem["char_count"] += len(formatted_msg)
    memory_engine.save_memory(mem)

    memory_engine.append_transcript(
        chat_id, "user", text,
        meta={"sender_name": sender, "is_group": is_group, "replied": False},
    )

    if mem["char_count"] > memory_engine.char_limit:
        memory_engine.trigger_summarize(
            chat_id, LM_STUDIO_URL, settings.get("selected_model"), log
        )

    return jsonify({"logged": True})


# --- BRIDGE ENDPOINTS (called by bridge.js) ---

@app.route("/api/bridge-log", methods=["POST"])
def bridge_log():
    log((request.json or {}).get("log", ""))
    return jsonify({"status": "logged"})


@app.route("/api/update-status", methods=["POST"])
def update_status():
    status = (request.json or {}).get("status", "Disconnected")
    state["whatsapp_status"] = status
    if status == "Connected":
        state["qr_data"] = ""
    return jsonify({"status": "synced"})


@app.route("/api/update-qr", methods=["POST"])
def update_qr():
    state["qr_data"] = (request.json or {}).get("qr", "")
    state["whatsapp_status"] = "Waiting"
    return jsonify({"status": "synced"})


@app.route("/api/check-bot-enabled", methods=["GET"])
def check_bot_enabled():
    """Bridge polls/checks this before processing any message at all."""
    return jsonify({"enabled": settings.get("bot_enabled", True)})


@app.route("/api/check-contact", methods=["POST"])
def check_contact():
    """Bridge calls this BEFORE sending to /api/chat so blocked contacts
    never even hit the LLM pipeline (saves tokens + keeps it instant).

    Also where new groups get their FIRST-TIME defaults applied:
    - default_group_policy decides whether a brand-new group starts
      blocked or allowed.
    - default_observer_for_groups decides whether a brand-new group starts
      in silent/observer mode (logs only, never replies, never types).
    These only apply once, on first sight of a chat_id - after that the
    admin's explicit choice in the panel always wins."""
    data = request.json or {}
    chat_id = data.get("chat_id", "")
    display_name = data.get("display_name", "")
    is_group = bool(data.get("is_group", False))

    default_status = "allowed"
    default_observer = False
    if is_group:
        default_status = settings.get("default_group_policy", "blocked")
        default_observer = bool(settings.get("default_observer_for_groups", True))

    contacts.touch(
        chat_id,
        display_name=display_name,
        is_group=is_group,
        timestamp=datetime.now(timezone.utc).isoformat(),
        default_status=default_status,
        default_observer=default_observer,
    )
    blocked = contacts.is_blocked(chat_id)
    observer = contacts.is_observer(chat_id)
    return jsonify({"blocked": blocked, "observer": observer})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_msg = data.get("message", "")
    chat_id = data.get("chat_id", "unknown")
    sender = data.get("sender_name", "User")
    is_group = bool(data.get("is_group", False))
    was_mentioned = bool(data.get("was_mentioned", False))

    # Master kill switch + per-contact block, checked again here as a
    # safety net even though the bridge should already filter these out.
    if not settings.get("bot_enabled", True):
        return jsonify({"parts": [], "skipped": "bot_disabled"})
    if contacts.is_blocked(chat_id):
        return jsonify({"parts": [], "skipped": "blocked"})

    state["total_messages_processed"] += 1
    log(f"📩 [{sender}]: {user_msg}")

    mem = memory_engine.load_memory(chat_id)
    formatted_msg = f"[{sender}]: {user_msg}"

    memory_engine.append_transcript(
        chat_id, "user", user_msg, meta={"sender_name": sender, "is_group": is_group}
    )

    mode = resolve_mode(chat_id, user_msg, is_group, was_mentioned)
    cfg = mode_config(mode)

    # Internet injection
    search_context = ""
    if settings.get("internet_enabled", False):
        log("🌐 Fetching real-time web context...")
        search_context = NexusSkills.fetch_web_context(user_msg)

    # Per-contact admin notes get injected as extra system context, e.g.
    # "this is my boss, stay formal" - lets the admin steer individual
    # relationships without editing character.md globally.
    contact_notes = contacts.get_notes(chat_id)

    payload = [{"role": "system", "content": load_persona()}]
    if contact_notes:
        payload.append({
            "role": "system",
            "content": f"Note about this specific contact/group: {contact_notes}",
        })
    payload.append({
        "role": "system",
        "content": f"Current mode: {mode.upper()}. "
                    + ("Keep it SHORT and casual." if mode == "casual"
                       else "You may reason and respond more thoroughly."),
    })
    if mem["summary"]:
        payload.append({"role": "system", "content": f"Prior context:\n{mem['summary']}"})
    for m in mem["messages"]:
        payload.append(m)
    payload.append({"role": "user", "content": formatted_msg + search_context})

    try:
        client = OpenAI(base_url=f"{LM_STUDIO_URL}/v1", api_key="lm-studio")
        response = client.chat.completions.create(
            model=settings.get("selected_model", "local-model"),
            messages=payload,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
        reply = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        tokens_used = getattr(usage, "total_tokens", None) if usage else None
        log(f"🚀 Reply generated ({mode} mode, cap={cfg['max_tokens']}"
            + (f", used={tokens_used}" if tokens_used is not None else "") + ")")

        # Save LLM-facing memory
        mem["messages"].append({"role": "user", "content": formatted_msg})
        mem["messages"].append({"role": "assistant", "content": reply})
        mem["char_count"] += len(formatted_msg) + len(reply)
        memory_engine.save_memory(mem)

        memory_engine.append_transcript(
            chat_id, "assistant", reply,
            meta={"mode": mode, "max_tokens": cfg["max_tokens"], "tokens_used": tokens_used},
        )

        if mem["char_count"] > memory_engine.char_limit:
            memory_engine.trigger_summarize(
                chat_id, LM_STUDIO_URL, settings.get("selected_model"), log
            )

        # Humanize: split into bubbles / compute delays. The bridge sends
        # each part with its own typing pause - this is the actual fix for
        # "doesn't type like a real human".
        parts = humanize_reply(
            reply,
            strategy=settings.get("pacing_strategy", "both"),
            cps=settings.get("typing_cps", 14),
            max_chunks=settings.get("max_chunks", 4),
        )

        return jsonify({"parts": parts, "mode": mode})

    except Exception as e:
        log(f"❌ AI Core Error: {str(e)}")
        memory_engine.append_transcript(chat_id, "system_event", f"error: {str(e)}")
        return jsonify({"parts": [{"text": "ugh my brain lagged, try again in a sec", "delay_ms": 800}]}), 200


if __name__ == "__main__":
    app.run(port=5000, debug=True, use_reloader=False)
