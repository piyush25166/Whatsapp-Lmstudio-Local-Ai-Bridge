from duckduckgo_search import DDGS


class NexusSkills:
    @staticmethod
    def fetch_web_context(query, max_results=2, char_limit=250):
        """Fetches live web data and aggressively trims it to save LLM tokens."""
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

            return "\n\n[LIVE WEB DATA INJECTED]:\n" + "\n".join(trimmed_facts)
        except Exception as e:
            return f"\n\n[SYSTEM NOTE: Web search temporarily unavailable: {str(e)}]"
