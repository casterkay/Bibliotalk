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

---

## Draft (Not Implemented): Top-Level Schema (v2)

This v2 schema is **not implemented** in `services/memory_service` as of 2026-03-06.
The CLI/server currently accept **only** `version: "1"` and must reject v2 inputs with a clear error.

`v2` extends `v1` with non-interactive web and document URL ingestion, plus blog-specialized discovery.

- `version` (string, required): `"2"`
- `run_name` (string, optional): human-friendly label
- `defaults` (object, optional):
  - `user_id` (string, optional): default EverMemOS user/tenant
  - `platform` (string, optional): default platform label
  - `chunking` (object, optional): default chunking preferences (size targets, transcript mode, etc.)
- `sources` (list, required): list of source items

## Source Item Schema (v2)

Each source item MUST include enough metadata for attribution and stable IDs. `v2` allows `external_id`
to be omitted for URL-based modes; the CLI derives it deterministically from the canonicalized URL.

- `user_id` (string, required if not provided in defaults)
- `platform` (string, required if not provided in defaults): e.g. `local`, `gutenberg`, `youtube`, `web`
- `external_id` (string, optional for URL-based modes): stable per platform (file hash, Gutenberg ebook ID, YouTube video ID, canonical URL hash, etc.)
- `title` (string, required): for `crawl_seed_url`, this is a seed label; discovered pages will use extracted titles.
- `source_url` (string, optional but recommended): canonical attribution URL (for URL-based modes, the URL itself is canonicalized and used)
- `author` (string, optional)
- `published_at` (string/date-time, optional)
- `raw_meta` (object, optional)

Exactly one content input mode MUST be provided:

- `text` (string): direct operator-provided text
- `file_path` (string): absolute path to local file
- `doc_url` (string): HTTP(S) URL to a document (pdf/docx/epub/html/…) which will be downloaded and converted to Markdown
- `web_url` (string): HTTP(S) URL to a single web page/article which will be extracted and converted to Markdown
- `rss_url` (string): RSS/Atom feed URL; the feed will be expanded into per-entry `web_url` ingests
- `crawl_seed_url` (string): seed URL for a blog-style crawl; discovery expands into per-page `web_url` ingests
- `gutenberg_id` (string/int): Gutenberg ebook ID (alternative to `external_id` when platform is `gutenberg`)
- `youtube_video_id` (string): YouTube video ID (alternative to `external_id` when platform is `youtube`)

Optional discovery options (v2):

- `max_items` (int, optional): maximum number of discovered pages to ingest (for `rss_url` / `crawl_seed_url`)
- `max_pages` (int, optional): maximum number of pages to fetch during discovery (for `crawl_seed_url`)

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

## Example (YAML, v2 web/doc/crawl)

```yaml
version: "2"
run_name: "blog-ingest"
defaults:
  user_id: "agent_uuid_or_tenant_id"
  platform: "web"
sources:
  - title: "One blog post"
    web_url: "https://example.com/blog/my-post"

  - title: "Remote PDF"
    platform: "local"
    doc_url: "https://example.com/files/paper.pdf"

  - title: "Site crawl seed (reviewable fan-out)"
    crawl_seed_url: "https://example.com/blog/"
    max_items: 50
    max_pages: 200
```

## Validation Rules

- The CLI MUST reject manifests missing required fields with a clear error message.
- The CLI MUST reject sources that imply interactive crawling (e.g., arbitrary `url` without a supported adapter) with an actionable error.
- Processing MUST continue for other sources if one source fails.
