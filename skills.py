"""
skills.py
---------
External "skills" the bot can call into. Currently just live web search,
trimmed aggressively so the internet toggle doesn't itself become a token
sink. Designed to be extended - add new @staticmethod functions here and
call them from app.py's chat() pipeline the same way fetch_web_context is
called.
"""

from duckduckgo_search import DDGS


class NexusSkills:
    @staticmethod
    def fetch_web_context(query, max_results=2, char_limit=250):
        """Fetches live web data and aggressively trims it to save tokens."""
        try:
            results = DDGS().text(keywords=query, max_results=max_results)
            if not results:
                return ""

            trimmed_facts = []
            for r in results:
                title = r.get("title", "Fact")
                body = r.get("body", "")
                short_body = (
                    body[:char_limit] + "..." if len(body) > char_limit else body
                )
                trimmed_facts.append(f"- {title}: {short_body}")

            return "\n\n[LIVE WEB DATA]:\n" + "\n".join(trimmed_facts)
        except Exception as e:
            return f"\n\n[SYSTEM NOTE: Web search unavailable: {str(e)}]"
