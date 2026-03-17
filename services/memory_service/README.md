# memory_service

This package now keeps only the ingestion primitives that still matter to the Discord MVP:

- YouTube transcript loading via a swappable provider service:
  - `yt-dlp` captions (subtitles + auto-captions when available)
  - `youtube-transcript-api` (optional extra; fallback)
- YouTube metadata discovery via `yt-dlp`
- RSS feed parsing via `feedparser`
- deterministic chunking
- local indexing and EverMemOS ingest helpers

Removed from this package:

- legacy HTTP server entrypoints
- document/blog/web-page ingestion adapters
- figure JSON conversion scripts
- Matrix-era or non-YouTube ingestion surfaces

## Development

- Sync deps in the workspace: `UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras`
- Run tests: `uv --directory services/memory_service run --package memory_service -m pytest`
- Unified CLI help: `uv run --package bt_cli bibliotalk --help`

## Optional Extras

- `ingest`: installs `youtube-transcript-api`
- `web`: installs `feedparser`

## Notes

- `yt-dlp` must be available on `PATH` for YouTube metadata and playlist discovery.
- Runtime config (env vars):
  - `BIBLIOTALK_YOUTUBE_TRANSCRIPT_PROVIDERS` (default: `yt_dlp,youtube_transcript_api`)
  - `BIBLIOTALK_YOUTUBE_TRANSCRIPT_LANGS` (comma-separated, optional; ex: `en,en-US`)
  - `BIBLIOTALK_YOUTUBE_ALLOW_AUTO_CAPTIONS` (default: `true`)
  - `BIBLIOTALK_YT_DLP_COOKIEFILE` (optional; improves access on restricted videos)
  - `BIBLIOTALK_YT_DLP_IMPERSONATE` (default: `chrome`; set empty to disable)
  - `BIBLIOTALK_YOUTUBE_REQUEST_DELAY_S` (default: `0.25`; base delay before each YouTube request)
  - `BIBLIOTALK_YOUTUBE_REQUEST_JITTER_S` (default: `0.5`; added random delay range)
- The target replacement runtime is documented in `specs/003-discord-bot/plan.md`.
