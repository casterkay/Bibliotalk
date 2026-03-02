# Contract: Ingestion Manifest (Batch Input)

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`  
**Created**: 2026-03-01

This contract defines the batch ingestion manifest format. The ingestion CLI must accept this manifest and process each source independently.

## Format

- Supported encodings: UTF-8
- Supported file formats: YAML or JSON
- Schema versioning: required top-level `version`

## Top-Level Schema (v1)

- `version` (string, required): `"1"`
- `run_name` (string, optional): human-friendly label
- `defaults` (object, optional):
  - `user_id` (string, optional): default EverMemOS user/tenant
  - `platform` (string, optional): default platform label
  - `chunking` (object, optional): default chunking preferences (size targets, transcript mode, etc.)
- `sources` (list, required): list of source items

## Source Item Schema (v1)

Each source item MUST include enough metadata for attribution and stable IDs.

- `user_id` (string, required if not provided in defaults)
- `platform` (string, required if not provided in defaults): e.g. `local`, `gutenberg`, `youtube`
- `external_id` (string, required): stable per platform (file hash, Gutenberg ebook ID, YouTube video ID, etc.)
- `title` (string, required)
- `source_url` (string, optional but recommended)
- `author` (string, optional)
- `published_at` (string/date-time, optional)
- `raw_meta` (object, optional)

Exactly one content input mode MUST be provided:

- `text` (string): direct operator-provided text
- `file_path` (string): absolute path to local file
- `gutenberg_id` (string/int): Gutenberg ebook ID (alternative to `external_id` when platform is `gutenberg`)
- `youtube_video_id` (string): YouTube video ID (alternative to `external_id` when platform is `youtube`)

## Example (YAML)

```yaml
version: "1"
run_name: "roster-sample"
defaults:
  user_id: "agent_uuid_or_tenant_id"
sources:
  - platform: "local"
    external_id: "walden-ch1"
    title: "Walden — Chapter 1"
    source_url: "https://example.com/walden"
    file_path: "/Users/tcai/Documents/walden_ch1.txt"

  - platform: "local"
    external_id: "inline-note-1"
    title: "Operator Note"
    text: "A short inline note that should be ingested as a single source."

  - platform: "gutenberg"
    external_id: "3330"
    title: "The Analects"
    source_url: "https://www.gutenberg.org/ebooks/3330"
    gutenberg_id: "3330"

  - platform: "youtube"
    external_id: "dQw4w9WgXcQ"
    title: "Example Talk"
    source_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    youtube_video_id: "dQw4w9WgXcQ"
```

## Validation Rules

- The CLI MUST reject manifests missing required fields with a clear error message.
- The CLI MUST reject sources that imply interactive crawling (e.g., arbitrary `url` without a supported adapter) with an actionable error.
- Processing MUST continue for other sources if one source fails.
