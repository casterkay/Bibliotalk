# Bibliotalk Operations (Unified CLI)

This repo is operated via the unified `bibliotalk` CLI (package: `bt_cli`).

## Config precedence

For all commands:

1. Explicit CLI flags (e.g. `--db`, `--log-level`)
2. Environment variables (from repo-root `.env` if present)
3. Built-in defaults

## Required environment variables

- EverMemOS: `EMOS_BASE_URL`, `EMOS_API_KEY`
- Discord: `DISCORD_TOKEN`
- Gemini (recommended for production-quality talk replies): `GOOGLE_API_KEY`
- Admin / operator APIs: `BIBLIOTALK_ADMIN_TOKEN`

Optional:

- `BIBLIOTALK_DB_PATH` (defaults to `~/.bibliotalk/bibliotalk.db`)
- `BIBLIOTALK_WEB_URL` (defaults to `https://www.bibliotalk.space`)

## Common workflows

### 1) Seed or update an agent

```
uv run --package bt_cli bibliotalk agent seed \
  --agent alan-watts \
  --subscription-url https://www.youtube.com/@AlanWattsOrg \
  --guild-id <GUILD_ID> \
  --channel-id <FEED_CHANNEL_ID>
```

### 2) Run the collector (poll + ingest)

```
uv run --package bt_cli bibliotalk collector run --agent alan-watts
```

Run one cycle and exit:

```
uv run --package bt_cli bibliotalk collector run --agent alan-watts --once
```

### 3) Request a manual one-shot ingest of a specific video

```
uv run --package bt_cli bibliotalk ingest request --agent alan-watts --video-id <YOUTUBE_VIDEO_ID>
uv run --package bt_cli bibliotalk collector run --agent alan-watts --once
```

### 4) Run the Discord bot

```
uv run --package bt_cli bibliotalk discord run
```

### 5) Publish pending feeds (without restarting the bot)

```
uv run --package bt_cli bibliotalk feed publish
```

Limit to one agent:

```
uv run --package bt_cli bibliotalk feed publish --agent alan-watts
```

### 6) Repair feed publication for one video

Status:

```
uv run --package bt_cli bibliotalk feed status --agent alan-watts --video-id <YOUTUBE_VIDEO_ID>
```

Retry failed posts and publish missing pieces:

```
uv run --package bt_cli bibliotalk feed retry-failed --agent alan-watts --video-id <YOUTUBE_VIDEO_ID>
```

Resume publishing for a single video without resetting state:

```
uv run --package bt_cli bibliotalk feed republish --agent alan-watts --video-id <YOUTUBE_VIDEO_ID>
```

### 7) Run the Memories API

```
uv run --package bt_cli bibliotalk memories run --host 0.0.0.0 --port 8080
```

### 8) Run the Operator Web UI

The WebUI serves a static frontend and an authenticated `/api/*` backend.

```
uv run --package bt_cli bibliotalk webui run --host 0.0.0.0 --port 8090
```

## Notes

- Secrets must be provided via environment variables (not CLI arguments).
- `yt-dlp` must be on `PATH` for YouTube discovery and metadata.
