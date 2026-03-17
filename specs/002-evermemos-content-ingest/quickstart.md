# Quickstart: EverMemOS Content Ingestion Package

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`
**Created**: 2026-03-01

This quickstart describes the intended developer/operator workflow for the ingestion package once implemented.

## Prerequisites

- `uv` (workspace; see repo root)
- EverMemOS base URL and API key (if required by the target EverMemOS instance)
- Curated source content (text/files/transcripts) and source attribution metadata (title + canonical link)

Install deps (from repo root):

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras
```

## Configuration

Environment variables (recommended):

- `EMOS_BASE_URL` (required): EverMemOS base URL, e.g. `https://<host>`
- `EMOS_API_KEY` (optional): API key for `Authorization: Bearer ...`
- `EMOS_TIMEOUT_S` (optional): request timeout
- `EMOS_RETRIES` (optional): retry count for transient failures
- `INGEST_INDEX_PATH` (optional): path to the local SQLite ingestion index

## Ingest One Source (P1)

Intended CLI shape:

- Ingest local text:
  - `uv run --package memory_service -m memory_service ingest text --user-id <USER_ID> --title "<TITLE>" --canonical-url "<URL>" --platform local --external-id "<ID>" --text "<TEXT>"`
- Ingest a local file:
  - `uv run --package memory_service -m memory_service ingest file --user-id <USER_ID> --title "<TITLE>" --canonical-url "<URL>" --platform local --external-id "<ID>" --path /absolute/path/to/file.txt`

Expected output:
- human-readable summary to stdout
- a JSON report file written to an operator-specified `--report-path`, or by default to `.memory_service/reports/<run_id>.json`

## Re-Run Safely (P2)

Re-running the same command with unchanged content is expected to:
- skip unchanged segments (no duplicates)
- report `skipped_unchanged` counts per source

## Batch Ingest (P3)

Intended CLI shape:

- `uv run --package memory_service -m memory_service ingest manifest --path /absolute/path/to/manifest.yaml`

The manifest format and report format are defined in:
- `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/contracts/ingest-manifest.md`
- `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/contracts/report-format.md`

## Non-Interactive Constraint

## Local E2E with agents_service

For the **full local “chat with spirits” flow** (Synapse + Element Web + `agents_service` + this ingestion package), you can use the agents_service quickstart’s one-shot script:

```bash
chmod +x deploy/local/bin/*.sh
deploy/local/bin/setup-all.sh
```

This will:

- run the local ingestion manifest at `deploy/local/ingest/manifest.yaml` against EverMemOS,
- write reports + segment cache under `.memory_service/`, and
- import the segment cache into the `agents_service` SQLite store for citations.

See `specs/001-agent-service/quickstart.md` for the end-to-end Matrix flow and how to chat with Spirits once data is ingested.

If a source requires interactive browsing (dynamic rendering, login, anti-bot challenges), ingestion must fail with an actionable error. Playwright/browser crawling is explicitly deferred in this feature.
