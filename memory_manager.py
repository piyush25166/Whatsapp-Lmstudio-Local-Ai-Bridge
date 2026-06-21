"""
memory_manager.py
------------------
Two separate concerns, kept deliberately apart:

1. LLM-FACING MEMORY (history.json / summary.txt)
   The rolling context actually sent to the model. Gets compressed into a
   summary once it grows past char_limit, exactly like before - this is
   what keeps token usage sane over a long-running chat.

2. ADMIN-FACING TRANSCRIPT (transcript.jsonl)
   A full, append-only, NEVER-trimmed log of every message in and out of
   every chat, with timestamps, sender name, and which mode/token-cap was
   used for that reply. This is what the admin panel's "view chats" screen
   reads from. It is intentionally never summarized or deleted by the bot
   itself - only the admin's "wipe" action clears it, alongside the LLM
   memory.
"""

import os
import re
import json
import threading
from datetime import datetime, timezone
from openai import OpenAI


class MemoryManager:
    def __init__(self, base_dir="memories", char_limit=6000):
        self.base_dir = base_dir
        self.char_limit = char_limit
        os.makedirs(self.base_dir, exist_ok=True)

    def get_safe_id(self, chat_id):
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", chat_id)

    def _user_dir(self, chat_id):
        folder = self.get_safe_id(chat_id)
        user_dir = os.path.join(self.base_dir, folder)
        os.makedirs(user_dir, exist_ok=True)
        return user_dir

    # ---------- LLM-facing memory ----------

    def load_memory(self, chat_id):
        user_dir = self._user_dir(chat_id)
        hist_path = os.path.join(user_dir, "history.json")
        sum_path = os.path.join(user_dir, "summary.txt")

        messages = []
        summary = ""

        if os.path.exists(hist_path):
            try:
                with open(hist_path, "r", encoding="utf-8") as f:
                    messages = json.load(f)
            except Exception:
                messages = []
        if os.path.exists(sum_path):
            with open(sum_path, "r", encoding="utf-8") as f:
                summary = f.read()

        char_count = sum(len(m.get("content", "")) for m in messages)
        return {
            "chat_id": chat_id,
            "dir": user_dir,
            "messages": messages,
            "summary": summary,
            "char_count": char_count,
        }

    def save_memory(self, mem):
        with open(os.path.join(mem["dir"], "history.json"), "w", encoding="utf-8") as f:
            json.dump(mem["messages"], f, indent=2)
        with open(os.path.join(mem["dir"], "summary.txt"), "w", encoding="utf-8") as f:
            f.write(mem["summary"])

    def get_all_memories(self):
        """Used by the Admin UI to list all active chats (lightweight)."""
        mems = []
        if not os.path.isdir(self.base_dir):
            return mems
        for folder in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, folder)
            if os.path.isdir(path):
                hist_path = os.path.join(path, "history.json")
                msg_count = 0
                if os.path.exists(hist_path):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            msg_count = len(json.load(f))
                    except Exception:
                        pass
                mems.append({"id": folder, "message_count": msg_count})
        return mems

    def wipe_memory(self, chat_id):
        """Wipes BOTH the LLM memory and the full transcript for this chat."""
        user_dir = self._user_dir(chat_id)
        if os.path.exists(user_dir):
            import shutil
            shutil.rmtree(user_dir)
            return True
        return False

    def trigger_summarize(self, chat_id, lm_url, model_name, logger):
        threading.Thread(
            target=self._summarize_task, args=(chat_id, lm_url, model_name, logger)
        ).start()

    def _summarize_task(self, chat_id, lm_url, model_name, logger):
        mem = self.load_memory(chat_id)
        convo = "\n".join([f"{m['role']}: {m['content']}" for m in mem["messages"]])
        prompt = (
            "Summarize this conversation in under 1000 characters. "
            "Keep facts and names intact.\n\n" + convo
        )
        try:
            client = OpenAI(base_url=f"{lm_url}/v1", api_key="lm-studio")
            res = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            mem["summary"] = res.choices[0].message.content
            mem["messages"] = []
            mem["char_count"] = 0
            self.save_memory(mem)
            logger(f"✅ Memory compressed for {self.get_safe_id(chat_id)}")
        except Exception as e:
            logger(f"❌ Compression failed: {str(e)}")

    # ---------- Admin-facing full transcript ----------

    def append_transcript(self, chat_id, role, text, meta=None):
        """Appends one line to the never-trimmed transcript log.

        role: "user" | "assistant" | "system_event"
        meta: optional dict, e.g. {"sender_name": ..., "mode": ..., "tokens_capped": ...}
        """
        user_dir = self._user_dir(chat_id)
        path = os.path.join(user_dir, "transcript.jsonl")
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "text": text,
            "meta": meta or {},
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_transcript(self, chat_id, limit=200):
        """Returns the most recent `limit` transcript entries, oldest first."""
        user_dir = self._user_dir(chat_id)
        path = os.path.join(user_dir, "transcript.jsonl")
        if not os.path.exists(path):
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        return entries[-limit:]
