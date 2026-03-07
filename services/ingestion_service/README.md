# ingestion_service

This package now keeps only the ingestion primitives that still matter to the Discord MVP:

- YouTube transcript loading via `youtube-transcript-api`
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
- Run tests: `uv --directory services/ingestion_service run --package ingestion_service -m pytest`

## Optional Extras

- `ingest`: installs `youtube-transcript-api`
- `web`: installs `feedparser`

## Notes

- `yt-dlp` must be available on `PATH` for YouTube metadata and playlist discovery.
- The target replacement runtime is documented in `specs/003-discord-bot/plan.md`.
