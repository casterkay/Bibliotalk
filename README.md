# Bibliotalk

This repository is being reduced to the Discord-era MVP described in `specs/003-discord-bot/`.

What remains in scope:

- `packages/bt_common/`: shared EverMemOS client, config loading, logging, and common exceptions.
- `services/ingestion_service/`: retained YouTube/RSS ingestion primitives, chunking, and EverMemOS indexing logic.
- `services/agents_service/`: retained Gemini-grounded agent library, evidence models, and citation tooling.
- `specs/002-evermemos-content-ingest/` and `specs/003-discord-bot/`: active design artifacts.

Out-of-scope legacy surfaces such as Matrix transport, voice runtimes, SQLAdmin, Synapse deploy assets, and unrelated research docs have been removed.

## Development

- Sync deps (workspace): `UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras`
- Run agent tests: `uv --directory services/agents_service run --package agents_service -m pytest`
- Run ingestion tests: `uv --directory services/ingestion_service run --package ingestion_service -m pytest`
- Run shared package tests: `uv --directory packages/bt_common run --package bt_common -m pytest`

## Notes

- `yt-dlp` must be available on `PATH` for YouTube metadata and discovery.
- The canonical target architecture is documented in `specs/003-discord-bot/plan.md`.
