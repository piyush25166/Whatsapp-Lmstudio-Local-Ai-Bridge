"""
settings_manager.py
--------------------
Single source of truth for every global control the admin panel exposes.
Persisted to settings.json so changes survive a restart. app.py reads this
on every request (cheap - it's a small dict, no need to cache aggressively)
so panel changes take effect on the very next incoming message with no
restart needed.
"""

import os
import json
import threading

SETTINGS_PATH = "settings.json"
_lock = threading.Lock()

DEFAULTS = {
    # Global behavior toggles
    "internet_enabled": False,
    "bot_enabled": True,            # master kill switch - off = bridge stops replying to anyone

    # Mode token caps - this is the actual fix for "3k tokens for 6 lines"
    "casual_max_tokens": 120,
    "thinking_max_tokens": 700,

    # Mode temperature (kept separate so casual can be snappier/safer,
    # thinking can be a little more exploratory)
    "casual_temperature": 0.8,
    "thinking_temperature": 0.6,

    # Default mode logic
    # "casual_dm_mention_group" = casual everywhere by default, thinking
    # only triggers on the literal "@think" tag in the message text.
    "thinking_trigger_tag": "@think",

    # Group reply gating
    # True  = only reply in groups when @mentioned, replied-to, or @think
    #         tagged. The bot still SEES and remembers every group message
    #         either way - this only controls whether it talks.
    # False = reply to every message in every group, same as a DM.
    "require_mention_in_groups": True,
    "log_unreplied_group_messages": True,

    # Default-deny for groups: any NEW group the bot has never seen gets
    # auto-blocked the instant it's registered. You then explicitly allow
    # only the specific groups you want (set their contact status to
    # "allowed" in the panel). DMs are unaffected by this - they use their
    # own normal allowed-by-default behavior.
    "default_group_policy": "blocked",   # "blocked" | "allowed"

    # Even an explicitly allowed group starts in observer mode: the bot
    # logs everything, replies to nothing, shows no typing indicator. You
    # flip a specific group's observer mode off in the panel once you
    # actually want it to start replying there.
    "default_observer_for_groups": True,

    # Humanizer / pacing
    "pacing_strategy": "both",      # "delay" | "chunked" | "both"
    "typing_cps": 14,               # characters-per-second assumed typing speed
    "max_chunks": 4,

    # Model
    "selected_model": "local-model",

    # Memory
    "memory_char_limit": 6000,
}


class SettingsManager:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # merge so new defaults added in future versions don't
                # disappear just because an old settings.json is missing them
                merged = dict(DEFAULTS)
                merged.update(loaded)
                self._data = merged
            except Exception:
                self._data = dict(DEFAULTS)
        else:
            self._save()

    def _save(self):
        with _lock:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self.path)

    def get(self, key, fallback=None):
        return self._data.get(key, fallback)

    def get_all(self):
        return dict(self._data)

    def update(self, updates: dict):
        """Validates known keys' types loosely, ignores unknown keys, saves."""
        for key, value in updates.items():
            if key not in DEFAULTS:
                continue
            self._data[key] = value
        self._save()
        return self.get_all()

    def reset_to_defaults(self):
        self._data = dict(DEFAULTS)
        self._save()
        return self.get_all()
