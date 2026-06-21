"""
prompt_manager.py
------------------
Lets the admin edit the persona LIVE from the panel, without touching files
on disk by hand and without restarting anything.

Two layers, both editable from the panel:

1. PERSONA (character.md + skill.md content) - the core "who you are and
   how you talk" instructions. Editable as one combined text block in the
   panel. Saved to prompt_overrides.json once edited; the original
   character.md/skill.md files on disk are left untouched so there's always
   a known-good fallback via "Revert to file".

2. GLOBAL GUIDANCE - a short free-text note layered on top of the persona
   for quick day-to-day steering ("be extra sarcastic today", "we're
   planning a trip, bring it up if relevant") without editing the whole
   persona. Cleared independently of the persona.

Precedence when building the system prompt (see app.py load_persona()):
    persona override (if set) OR character.md+skill.md from disk
    + global guidance (if set)
    + per-contact notes (handled separately in contact_manager.py)
"""

import os
import json
import threading

PROMPT_PATH = "prompt_overrides.json"
_lock = threading.Lock()

DEFAULTS = {
    "persona_override": None,   # None = use character.md + skill.md from disk
    "global_guidance": "",      # "" = no extra guidance layered on top
}


class PromptManager:
    def __init__(self, path=PROMPT_PATH):
        self.path = path
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                merged = dict(DEFAULTS)
                merged.update(loaded)
                self._data = merged
            except Exception:
                self._data = dict(DEFAULTS)

    def _save(self):
        with _lock:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self.path)

    # ---------- persona override ----------

    def get_persona_override(self):
        return self._data.get("persona_override")

    def set_persona_override(self, text):
        """Pass None or '' to clear the override and fall back to the
        character.md + skill.md files on disk."""
        self._data["persona_override"] = text if text else None
        self._save()

    def revert_persona_to_disk(self):
        self._data["persona_override"] = None
        self._save()

    # ---------- global guidance ----------

    def get_global_guidance(self):
        return self._data.get("global_guidance", "")

    def set_global_guidance(self, text):
        self._data["global_guidance"] = text or ""
        self._save()

    def clear_global_guidance(self):
        self._data["global_guidance"] = ""
        self._save()

    # ---------- combined read for the panel ----------

    def get_all(self):
        return dict(self._data)
