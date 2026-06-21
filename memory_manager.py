import os
import re
import json
import threading
from openai import OpenAI


class MemoryManager:
    def __init__(self, base_dir="memories", char_limit=6000):
        self.base_dir = base_dir
        self.char_limit = char_limit
        os.makedirs(self.base_dir, exist_ok=True)

    def get_safe_id(self, chat_id):
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", chat_id)

    def load_memory(self, chat_id):
        folder = self.get_safe_id(chat_id)
        user_dir = os.path.join(self.base_dir, folder)
        os.makedirs(user_dir, exist_ok=True)

        hist_path = os.path.join(user_dir, "history.json")
        sum_path = os.path.join(user_dir, "summary.txt")

        messages = []
        summary = ""

        if os.path.exists(hist_path):
            with open(hist_path, "r", encoding="utf-8") as f:
                messages = json.load(f)
        if os.path.exists(sum_path):
            with open(sum_path, "r", encoding="utf-8") as f:
                summary = f.read()

        char_count = sum(len(m.get("content", "")) for m in messages)
        return {
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
        """Used by the Admin UI to list all active chats."""
        mems = []
        for folder in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, folder)
            if os.path.isdir(path):
                hist_path = os.path.join(path, "history.json")
                msg_count = 0
                if os.path.exists(hist_path):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            msg_count = len(json.load(f))
                    except:
                        pass
                mems.append({"id": folder, "message_count": msg_count})
        return mems

    def wipe_memory(self, chat_id):
        folder = self.get_safe_id(chat_id)
        user_dir = os.path.join(self.base_dir, folder)
        if os.path.exists(user_dir):
            import shutil

            shutil.rmtree(user_dir)
            return True
        return False

    def trigger_summarize(self, chat_id, lm_url, model_name, logger):
        """Fires in the background so WhatsApp doesn't lag while compressing memory."""
        threading.Thread(
            target=self._summarize_task, args=(chat_id, lm_url, model_name, logger)
        ).start()

    def _summarize_task(self, chat_id, lm_url, model_name, logger):
        mem = self.load_memory(chat_id)
        convo = "\n".join([f"{m['role']}: {m['content']}" for m in mem["messages"]])
        prompt = f"Summarize this conversation in under 1000 characters. Keep facts and names intact.\n\n{convo}"

        try:
            client = OpenAI(base_url=f"{lm_url}/v1", api_key="lm-studio")
            res = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            mem["summary"] = res.choices[0].message.content
            mem["messages"] = []
            mem["char_count"] = 0
            self.save_memory(mem)
            logger(f"✅ Memory compressed for {self.get_safe_id(chat_id)}")
        except Exception as e:
            logger(f"❌ Compression failed: {str(e)}")
