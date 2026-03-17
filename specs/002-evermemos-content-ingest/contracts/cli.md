# Contract: CLI Commands (memory_service)

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`
**Created**: 2026-03-01

This contract defines the CLI surface area. The CLI is the primary operator interface and must remain stable.

## Entry Points

- Module: `python -m memory_service ...`
- Workspace (recommended): `uv run --package memory_service -m memory_service ...`
- (Optional packaging) Console script: `evermemos-ingest ...`

## Global Options

- `--emos-base-url` (string, optional if `EMOS_BASE_URL` is set)
- `--emos-api-key` (string, optional if `EMOS_API_KEY` is set; must not be echoed in logs)
- `--index-path` (string, optional if `INGEST_INDEX_PATH` is set)
- `--report-path` (string, optional): where to write the JSON report for the run
- `--log-level` (string, optional): `debug|info|warning|error`

## Commands

### 1) `ingest text`

Ingest operator-provided text as a single source.

Required:
- `--user-id`
- `--platform`
- `--external-id`
- `--title`
- `--text`

Optional:
- `--canonical-url`
- `--author`
- `--published-at`

### 2) `ingest file`

Ingest a local file as a single source.

Required:
- `--user-id`
- `--platform`
- `--external-id`
- `--title`
- `--path` (absolute path)

Optional:
- `--canonical-url`, `--author`, `--published-at`

### 3) `ingest web`

Ingest a single web page/article as a single source (non-interactive; static HTML extraction).

Required:
- `--user-id`
- `--url`

Optional:
- `--platform` (default: `web`)
- `--external-id` (defaults to a deterministic hash of the canonicalized URL)
- `--title` (falls back to extracted title, then URL)
- `--author`
- `--min-words` (default: `80`)

### 4) `ingest doc-url`

Download a remote document (pdf/docx/epub/html/…) and ingest its extracted Markdown as a single source.

Required:
- `--user-id`
- `--url`

Optional:
- `--platform` (default: `local`)
- `--external-id` (defaults to a deterministic hash of the canonicalized URL)
- `--title` (defaults to URL)
- `--canonical-url`, `--author`, `--published-at`

### 5) `ingest manifest`

Batch ingest one or more sources described by a manifest file.

Required:
- `--path` (absolute path to YAML/JSON manifest)

### 6) `crawl rss`

Expand an RSS/Atom feed into a reviewable manifest (v2) containing per-entry `web_url` items.

Required:
- `--rss-url`
- `--user-id`
- `--out-path` (path to write YAML manifest)

Optional:
- `--platform` (default: `web`)
- `--max-items` (default: `50`)

### 7) `crawl blog`

Discover blog-post URLs from a seed and write a reviewable manifest (v2) containing per-page `web_url` items.
Discovery is non-interactive and uses RSS/Atom autodiscovery, sitemaps, then a bounded same-host crawl fallback.

Required:
- `--seed-url`
- `--user-id`
- `--out-path` (path to write YAML manifest)

Optional:
- `--platform` (default: `web`)
- `--max-items` (default: `50`)
- `--max-pages` (default: `200`)

## Exit Codes

- `0`: all sources ingested successfully (or skipped as unchanged)
- `1`: at least one source failed
- `2`: invalid CLI usage or invalid manifest

## Output Guarantees

- The CLI MUST write a JSON report (see `report-format.md`) when `--report-path` is provided.
- The CLI MUST never print secrets (API key, auth header) even at debug log level.
