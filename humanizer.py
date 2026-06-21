"""
humanizer.py
------------
Makes replies feel like a person typing, not an API dumping a wall of text
instantly. Two independent knobs, both controllable from the admin panel:

1. PACING STRATEGY - how the reply is delivered:
   - "delay"   : wait a realistic amount of time, then send the whole reply
                 as one message.
   - "chunked" : split the reply into 2-4 natural bubbles (the way people
                 actually send multiple short texts in a row) and send each
                 one with its own typing pause in between.
   - "both"    : chunked AND with delay scaling — used by default; casual
                 mode tends to chunk more, thinking mode tends to delay more
                 (see app.py mode config).

2. SPEED - characters-per-second assumption used to compute delay, so a
   short "lol yeah" doesn't take 4 seconds and a long paragraph doesn't send
   instantly.

None of this is exposed to the model - it operates purely on the finished
text the LLM already generated. The bridge (bridge.js) calls /api/chat,
gets back a list of "parts" with per-part delay_ms, and sends them in
sequence with chat.sendStateTyping() before each one.
"""

import re
import random

# Tunable defaults - all overridable per-call from settings.json via app.py
DEFAULT_CPS = 14          # characters per second a "fast human typer" manages
MIN_DELAY_MS = 600        # never feel instant
MAX_DELAY_MS = 7000        # never make someone wait forever for a short reply
CHUNK_GAP_MS = (400, 1400)  # random gap range between chunks


def _typing_delay_ms(text, cps=DEFAULT_CPS):
    """Rough 'how long would a human take to type this' estimate."""
    seconds = len(text) / max(cps, 1)
    # add small human variance so it's not a perfectly linear function
    seconds *= random.uniform(0.85, 1.2)
    ms = int(seconds * 1000)
    return max(MIN_DELAY_MS, min(MAX_DELAY_MS, ms))


def _split_into_chunks(text, max_chunks=4):
    """Splits a reply into natural-feeling separate bubbles.

    Strategy: split on sentence boundaries / existing newlines, then merge
    short fragments back together so we don't end up sending one-word
    messages. Caps at max_chunks so a long thinking-mode answer doesn't get
    fragmented into 15 tiny bubbles.
    """
    text = text.strip()
    if not text:
        return []

    # Respect explicit newlines first (model may already separate thoughts)
    raw_parts = [p.strip() for p in text.split("\n") if p.strip()]

    # If no newlines, split on sentence enders
    if len(raw_parts) <= 1:
        raw_parts = re.split(r"(?<=[.!?])\s+", text)
        raw_parts = [p.strip() for p in raw_parts if p.strip()]

    if len(raw_parts) <= 1:
        return [text]

    # Merge short fragments so we don't send "lol" then "yeah" then "ok" as
    # three separate sends when they clearly belong together.
    merged = []
    buf = ""
    for part in raw_parts:
        if not buf:
            buf = part
        elif len(buf) < 20:
            buf += " " + part
        else:
            merged.append(buf)
            buf = part
    if buf:
        merged.append(buf)

    # Cap total chunk count by merging the tail together if needed
    while len(merged) > max_chunks:
        last = merged.pop()
        merged[-1] = merged[-1] + " " + last

    return merged


def humanize_reply(text, strategy="both", cps=DEFAULT_CPS, max_chunks=4):
    """
    Returns a list of dicts: [{"text": ..., "delay_ms": ...}, ...]

    The bridge sends each part in order, showing the typing indicator for
    `delay_ms` before each send. This is the single function app.py calls
    after getting a reply from the LLM.
    """
    text = (text or "").strip()
    if not text:
        return []

    if strategy == "delay":
        return [{"text": text, "delay_ms": _typing_delay_ms(text, cps)}]

    if strategy == "chunked":
        chunks = _split_into_chunks(text, max_chunks)
        parts = []
        for i, chunk in enumerate(chunks):
            # first chunk gets the full "thinking" delay, later chunks get a
            # shorter natural gap rather than a full re-read delay
            if i == 0:
                delay = _typing_delay_ms(chunk, cps)
            else:
                delay = random.randint(*CHUNK_GAP_MS)
            parts.append({"text": chunk, "delay_ms": delay})
        return parts

    # "both" (default): chunk it, but scale each chunk's delay by its own
    # length too, so longer chunks still take proportionally longer.
    chunks = _split_into_chunks(text, max_chunks)
    parts = []
    for i, chunk in enumerate(chunks):
        base = _typing_delay_ms(chunk, cps)
        if i > 0:
            base = min(base, random.randint(*CHUNK_GAP_MS) + 800)
        parts.append({"text": chunk, "delay_ms": base})
    return parts
