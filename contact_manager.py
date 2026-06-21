"""
contact_manager.py
-------------------
Tracks every chat_id (DM or group) the bot has ever seen, and lets the admin
panel control each one individually:

- status: "allowed" | "blocked"  (blocked contacts get zero replies)
- mode_override: None | "casual" | "thinking"  (None = use global default logic)
- notes: free text the admin can attach to a contact (e.g. "this is my boss,
  always be formal" / "close friend, can be blunt")
- display_name: last known sender/group name, so the admin panel shows a
  human label instead of a raw WhatsApp ID
- is_group: bool

Everything is persisted to contacts.json so it survives restarts. This file
intentionally has zero AI logic in it - it is pure account/permission state,
queried by app.py before any message reaches the model.
"""

import os
import json
import threading

CONTACTS_PATH = "contacts.json"
_lock = threading.Lock()


class ContactManager:
    def __init__(self, path=CONTACTS_PATH):
        self.path = path
        self._data = {}
        self._load()

    # ---------- persistence ----------

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        with _lock:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self.path)

    # ---------- core record management ----------

    def _default_record(self, chat_id, display_name="", is_group=False):
        return {
            "chat_id": chat_id,
            "display_name": display_name or chat_id,
            "is_group": is_group,
            "status": "allowed",
            "mode_override": None,
            "notes": "",
            "message_count": 0,
            "first_seen": None,
            "last_seen": None,
        }

    def touch(self, chat_id, display_name=None, is_group=False, timestamp=None):
        """Call this on every incoming message. Creates the record if new,
        updates last_seen / display_name / message_count if it exists."""
        if chat_id not in self._data:
            self._data[chat_id] = self._default_record(chat_id, display_name, is_group)
            self._data[chat_id]["first_seen"] = timestamp
        rec = self._data[chat_id]
        if display_name:
            rec["display_name"] = display_name
        rec["is_group"] = is_group
        rec["message_count"] = rec.get("message_count", 0) + 1
        rec["last_seen"] = timestamp
        self._save()
        return rec

    def get(self, chat_id):
        return self._data.get(chat_id)

    def get_all(self):
        """Returns contacts sorted by most recently active first."""
        items = list(self._data.values())
        items.sort(key=lambda r: r.get("last_seen") or "", reverse=True)
        return items

    # ---------- admin controls ----------

    def set_status(self, chat_id, status):
        """status must be 'allowed' or 'blocked'."""
        if status not in ("allowed", "blocked"):
            return False
        if chat_id not in self._data:
            self._data[chat_id] = self._default_record(chat_id)
        self._data[chat_id]["status"] = status
        self._save()
        return True

    def set_mode_override(self, chat_id, mode):
        """mode must be None, 'casual', or 'thinking'."""
        if mode not in (None, "casual", "thinking"):
            return False
        if chat_id not in self._data:
            self._data[chat_id] = self._default_record(chat_id)
        self._data[chat_id]["mode_override"] = mode
        self._save()
        return True

    def set_notes(self, chat_id, notes):
        if chat_id not in self._data:
            self._data[chat_id] = self._default_record(chat_id)
        self._data[chat_id]["notes"] = notes
        self._save()
        return True

    def delete_contact(self, chat_id):
        if chat_id in self._data:
            del self._data[chat_id]
            self._save()
            return True
        return False

    def is_blocked(self, chat_id):
        rec = self._data.get(chat_id)
        return bool(rec and rec.get("status") == "blocked")

    def get_mode_override(self, chat_id):
        rec = self._data.get(chat_id)
        if rec:
            return rec.get("mode_override")
        return None

    def get_notes(self, chat_id):
        rec = self._data.get(chat_id)
        return rec.get("notes", "") if rec else ""
