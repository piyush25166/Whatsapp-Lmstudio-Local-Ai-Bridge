# NEXUS WhatsApp Clone Bot — v2

## What changed from your version, and why

**1. Token bloat fixed (the "3k tokens for 6 lines" problem)**
The old code never passed `max_tokens` to the API, so the model free-ran
until it felt like stopping. Now every reply is generated with an explicit
cap, controlled from the panel:
- **Casual mode** (default): low cap, e.g. 120 tokens. This is what 95% of
  your DMs/group replies will use.
- **Thinking mode**: higher cap, e.g. 700 tokens. Only triggers when a
  message contains `@think`, or you force it for a specific contact from
  the panel.

**2. Doesn't type like a real human → fixed**
`humanizer.py` is new. After the LLM generates a reply, it:
- splits long replies into 2-4 separate WhatsApp bubbles (like a real
  person sending several texts in a row), and
- computes a realistic typing delay per bubble based on its length,
  so a one-word reply doesn't take 4 seconds and a paragraph doesn't
  appear instantly.
`bridge.js` shows the typing indicator and waits the computed delay before
sending each bubble. You control the strategy (delay-only / chunked /
both), typing speed, and max bubbles per reply — all from **Behavior &
Tokens** in the panel.

**3. Full admin visibility**
Every message in and out of every chat is now logged to a permanent,
never-trimmed transcript (`memories/<chat>/transcript.jsonl`), separate from
the LLM's own working memory (which still gets compressed/summarized to
keep token costs down). The **Live Chats** tab in the panel shows these
transcripts per contact in real time.

**4. User/group management**
New **Contacts & Groups** tab. For every chat that's ever messaged the bot:
- **Block/Allow** — blocked contacts get zero replies, and the request never
  even reaches the LLM (saves tokens too).
- **Mode override** — force a specific contact/group to always be casual or
  always be thinking, regardless of the `@think` tag.
- **Notes** — free text injected as extra system context for that one
  contact, e.g. "this is my manager, stay formal" or "close friend, be
  blunt" — lets you steer individual relationships without touching
  `character.md`.

**5. Master kill switch**
One toggle in the sidebar turns the whole bot off everywhere instantly,
without killing the bridge connection or losing your WhatsApp session.

## Setup

### 1. Python backend
```bash
cd WhatsApp_Lmstudio_Automation
pip install -r requirements.txt
python app.py
```
Runs on `http://127.0.0.1:5000`. Open that in your browser for the admin
panel.

### 2. Node bridge
```bash
npm install
node bridge.js
```
On first run it'll print/send a QR code to the panel's Dashboard tab — scan
it with WhatsApp on your phone (Linked Devices → Link a Device).

### 3. LM Studio
Make sure LM Studio's local server is running on `http://127.0.0.1:1234`
(Developer tab → Start Server) with a model loaded. The panel's Dashboard
shows whether it's detected.

## Filling in your persona — IMPORTANT

Open `character.md` and replace every `{{placeholder}}` with real, specific
detail about you — your actual name, real interests, actual phrases you use,
real inside jokes. The generic "robotic" feeling people get from these bots
almost always comes from a vague persona file, not the model. The more
specific and real the content, the less it sounds like an AI.

`skill.md` you generally don't need to touch — it's WhatsApp formatting +
memory/internet awareness rules and applies regardless of your persona.

## How modes work day to day

- **Casual** is the default everywhere — every DM, every group reply.
  Cheap, short, fast.
- **Thinking** only activates when:
  - the incoming message literally contains `@think` (anywhere in the
    text), e.g. `@think what's a good gift for a 30th birthday`, or
  - you've forced "Force Thinking" for that contact in the panel.
- A per-contact override in the panel always wins over the `@think` tag —
  if you set someone to "Force Casual," `@think` won't escalate them.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask backend — chat pipeline, mode/token logic, all admin API routes |
| `bridge.js` | WhatsApp connection — message intake, contact gating, humanized sending |
| `memory_manager.py` | Per-chat LLM memory (summarized) + permanent admin transcript log |
| `contact_manager.py` | Block/allow, mode override, notes — per chat_id, persisted to `contacts.json` |
| `settings_manager.py` | All panel-configurable settings, persisted to `settings.json` |
| `humanizer.py` | Splits replies into bubbles + computes realistic typing delays |
| `skills.py` | Live web search injection (internet toggle) |
| `character.md` | Your persona — **edit this** |
| `skill.md` | WhatsApp formatting + memory/internet behavior rules |
| `templates/index.html` | Admin panel UI |

## A note on intent

This is built to run your own clone for your own contacts, with you (the
admin) able to see every conversation and control it fully. It is not tuned
to deceive people who directly ask if they're talking to a bot, and the
notes/mode-override features are meant for steering tone per relationship,
not for extracting information from people. Keep it that way.
