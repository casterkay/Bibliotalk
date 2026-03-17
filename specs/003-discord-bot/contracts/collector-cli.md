# Contract: Discord Runtime Entry Point

**Package:** `discord_service`
**Entry point:** `python -m discord_service`
**Date:** 2026-03-10

The Discord runtime runs as a **single bot process**. YouTube ingestion/collection runs separately in `memory_service`.

---

## Process Entry Point

```
python -m discord_service
```

| Flag                 | Type  | Required | Description                                                                                  |
| -------------------- | ----- | -------- | -------------------------------------------------------------------------------------------- |
| `--db`               | `str` | No       | SQLite database path. Overrides `BIBLIOTALK_DB_PATH`. Default: `~/.bibliotalk/bibliotalk.db` |
| `--log-level`        | `str` | No       | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default: `INFO`                                  |
| `--command-guild-id` | `str` | No       | Optional guild ID to sync slash commands to for faster iteration                             |

Preferred unified CLI entrypoint:

```
bibliotalk discord run
```

---

## Environment Variables

All secrets MUST be provided via environment variables. They MUST NOT appear in command arguments, logs, or config files committed to the repository.

| Variable                         | Required | Description                                                                   |
| -------------------------------- | -------- | ----------------------------------------------------------------------------- |
| `EMOS_BASE_URL`                  | Yes      | EverMemOS API base URL                                                        |
| `EMOS_API_KEY`                   | Yes      | EverMemOS API key                                                             |
| `DISCORD_TOKEN`                  | Yes      | Discord bot token                                                             |
| `GOOGLE_API_KEY`                 | Yes      | Gemini API key (required for production-quality character replies)            |
| `BIBLIOTALK_DB_PATH`             | No       | SQLite database path (overridden by `--db`)                                   |
| `BIBLIOTALK_WEB_URL`             | No       | Base URL used for inline memory links (default: https://www.bibliotalk.space) |
| `DISCORD_COMMAND_GUILD_ID`       | No       | Optional guild ID for fast slash-command sync                                 |
| `BIBLIOTALK_ENABLE_AI_ROUTER`    | No       | Set to `true` to enable Gemini facilitator routing (default off)              |
| `BIBLIOTALK_ENABLE_AI_CONCIERGE` | No       | Set to `true` to enable Gemini DM concierge (default off)                     |

---

## Startup Sequence

```
1. Load env vars; fail fast if required secrets are missing
2. Create SQLAlchemy async engine (create tables if not exist for dev; run alembic for prod)
3. Load active figures from DB for the character directory
4. Instantiate talk service (/talk, /talks) and character agent orchestrator
5. Instantiate BibliotalkDiscordClient and connect
   └── on_ready:
       ├── sync slash commands (global or one guild)
       └── publish pending feed posts for all figures with DiscordMap entries
```

---

## Private Talks (DM → Threads)

- Users DM the bot and invoke `/talk Character A, Character B, ...`.
- The bot creates (or resumes) a **private thread** under a guild Talk Hub channel named `#bibliotalk`.
- Inside the thread, the user just sends messages; the bot routes each message to one or more characters.

---

## Deployment (Docker Compose)

```yaml
services:
  discord:
    image: bibliotalk/discord-service:latest
    command: ["python", "-m", "discord_service"]
    environment:
      EMOS_BASE_URL: "${EMOS_BASE_URL}"
      EMOS_API_KEY: "${EMOS_API_KEY}"
      DISCORD_TOKEN: "${DISCORD_TOKEN}"
      GOOGLE_API_KEY: "${GOOGLE_API_KEY}"
      BIBLIOTALK_DB_PATH: "/data/bibliotalk.db"
    volumes:
      - bibliotalk-data:/data
    restart: unless-stopped
```
