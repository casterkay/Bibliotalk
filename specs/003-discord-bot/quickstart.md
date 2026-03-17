# Quickstart: Local Development

**Feature:** `003-discord-bot`
**Date:** 2026-03-07

---

## Prerequisites

- Python 3.11+
- `uv` (workspace package manager)
- `yt-dlp` installed and on `$PATH`
- A Discord bot application and token (single bot) — create at https://discord.com/developers/applications
- An EverMemOS instance with API key
- A Google API key with Gemini access

---

## 1. Install dependencies

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras
```

---

## 2. Set up the database

Run Alembic migrations (from the `memory_service` directory):

```bash
cd services/memory_service
uv run alembic upgrade head
```

For local dev without Alembic, the process auto-creates tables on startup.

---

## 3. Configure environment

Create a `.env` file at the repo root (gitignored):

```env
# EverMemOS
EMOS_BASE_URL=https://your-evermemos-instance.example.com
EMOS_API_KEY=your-emos-api-key

# Gemini
GOOGLE_API_KEY=your-google-api-key

# SQLite database path (optional — defaults to ~/.bibliotalk/bibliotalk.db)
BIBLIOTALK_DB_PATH=/path/to/bibliotalk.db

# Public base URL used in inline memory links
BIBLIOTALK_WEB_URL=https://www.bibliotalk.space

# Discord bot token (single-bot runtime)
DISCORD_TOKEN=your-discord-bot-token

# Optional: speed up slash-command iteration by syncing to one guild
DISCORD_COMMAND_GUILD_ID=

# Optional: enable AI facilitator/concierge (defaults to deterministic fallback)
BIBLIOTALK_ENABLE_AI_ROUTER=
BIBLIOTALK_ENABLE_AI_CONCIERGE=
```

---

## 4. Seed a test figure

Use the helper script:

```bash
uv run --package bt_cli bibliotalk figure seed \
  --figure alan-watts \
  --display-name "Alan Watts" \
  --persona-summary "Philosopher and interpreter of Eastern philosophy." \
  --subscription-url https://www.youtube.com/@AlanWattsOrg \
  --guild-id YOUR_TEST_GUILD_ID \
  --channel-id YOUR_TEST_FEED_CHANNEL_ID
```

---

## 5. Run the bot

```bash
uv run --package bt_cli bibliotalk collector run --figure alan-watts
uv run --package bt_cli bibliotalk discord run
uv run --package bt_cli bibliotalk memory-pages run
```

Expected output:

```
INFO  [memory_service] Starting collector for figure: alan-watts (Alan Watts)
INFO  [discord_service] Starting discord runtime db_path=... command_guild_id=...
INFO  [discord_service] Connected to Discord as AlanWattsBot#1234
INFO  [discord_service] Feed publication complete figure_slug=alan-watts attempted=... published=... failed=...
INFO  [memory_service] Collector polling loop started (interval: 60 min)
```

---

## 6. Validate ingest (manual one-shot)

To test ingest without waiting for the polling interval, use the manual helper:

```bash
uv run --package bt_cli bibliotalk ingest request \
  --figure alan-watts \
  --video-id KNOWN_YOUTUBE_VIDEO_ID
```

Then process the manual request immediately:

```bash
uv run --package bt_cli bibliotalk collector run --figure alan-watts --once
```

---

## 7. Validate Discord feed

1. After a successful ingest, confirm the bot posts a parent message to your test feed channel.
2. A thread is created under the parent message.
3. Transcript batch messages appear in sequence inside the thread.
4. Re-run the bot process — confirm no duplicate parent message or thread.

---

## 8. Validate talks (DM → private thread)

1. In your test guild, create a Talk Hub channel named `#bibliotalk` and grant the bot permission to create private threads.
2. DM the bot and run `/talk Alan Watts`.
3. Open the created private thread and ask a question related to a successfully ingested video.
4. Confirm the response contains an inline link in the form `[text](https://www.bibliotalk.space/memory/alan-watts_20260101T120000Z)`.
5. Ask a question with no supporting evidence.
6. Confirm the character responds: *"I couldn't find relevant supporting evidence for that question."*

---

## Running tests

```bash
# memory_service unit tests
uv --directory services/memory_service run --package memory_service -m pytest

# agents_service unit tests (citation validation, BM25)
uv --directory services/agents_service run --package agents_service -m pytest

# discord_service tests
uv --directory services/discord_service run --package discord_service -m pytest

# bt_common contract tests
uv --directory packages/bt_common run --package bt_common -m pytest
```

---

## Docker Compose (local multi-figure)

```bash
cp deploy/local/.env.example deploy/local/.env
# fill in EMOS_BASE_URL, EMOS_API_KEY, GOOGLE_API_KEY, DISCORD_TOKEN_* values

docker compose -f deploy/local/docker-compose.yml up
```
