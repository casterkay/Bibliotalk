# Research: YouTube → EverMemOS → Discord Agent Bots

**Phase 0 output for:** `003-discord-bot`
**Date:** 2026-03-07
**Resolves all NEEDS CLARIFICATION items from Technical Context in plan.md**

---

## 1. YouTube Discovery — yt-dlp Flat Extraction

**Decision:** Use `yt-dlp --flat-playlist --dump-single-json {url}` to list channel or playlist entries without video downloads. Parse the `entries` array for `id`, `title`, `url`, `upload_date`, and `channel` fields. Compare against the `last_seen_external_id` cursor stored in `subscription_state` to compute the delta on each poll.

**Rationale:** Already proven in this codebase — `youtube_transcript.py` already shells out to `yt-dlp` for per-video metadata. Flat extraction avoids any video download; it returns structured JSON per playlist item and works for both channel URLs and playlist URLs without an API key. The `upload_date` field (`YYYYMMDD` string) combined with `last_published_at` cursor enables reliable incrementality.

**Alternatives considered:**
- YouTube Data API v3: requires API key, has daily quota. Rejected.
- RSS (YouTube channel feed): available as the `rss_feed.py` fallback path already in the repository; keep wired as FR-015 optional fallback when yt-dlp flat extraction fails for a given source; not the primary path.

---

## 2. SQLAlchemy 2.x Async with aiosqlite

**Decision:** Use `create_async_engine("sqlite+aiosqlite:///{db_path}")` with `async_sessionmaker(expire_on_commit=False)` and `DeclarativeBase`. Migrations via Alembic using the `run_sync` pattern (`await conn.run_sync(Base.metadata.create_all)` for tests; `alembic upgrade head` for production). All three packages reference the same DB path via `BIBLIOTALK_DB_PATH` environment variable.

**Rationale:** Operator directive. SQLAlchemy 2.x async integrates cleanly with the `asyncio` event loops used by both the collector (`memory_service`) and Discord gateway (`discord_service`). `aiosqlite` is non-blocking, preventing the Discord event loop from stalling during DB writes. Alembic migrations live with the shared schema in `packages/bt_store/`. Typed ORM models (`Mapped[T]`) prevent raw SQL query drift between services sharing the same schema. `expire_on_commit=False` is the standard pattern for async sessions to avoid lazy-load errors after commit.

**Alternatives considered:**
- Raw `aiosqlite` + manual SQL: Faster to bootstrap but loses type safety, migration tooling, and the ability to run `alembic upgrade head` on deployments. Rejected per operator directive.
- Tortoise ORM: Not in the existing stack. Rejected.

---

## 3. discord.py 2.x — Single-Bot, Multi-Agent Runtime

**Decision:** Subclass `discord.Client` (not `commands.Bot`) and use `app_commands.CommandTree` for `/talk` and `/talks`. Route:
- DM messages to a concierge helper, and DM slash commands to talk-thread creation.
- Thread messages in private talk threads to the grounded agent orchestrator.

YouTube ingestion/collection runs separately in `memory_service` and is not started by the Discord gateway process.

**Rationale:** `discord.Client` is the minimal surface needed: gateway events, DMs, threads, and REST actions for feed posting. A **single bot identity** should support multiple agents by loading active agents from the shared DB (`bt_store`) rather than running one process per agent/token.

**Alternatives considered:**
- Separate asyncio processes for bot and collector with IPC: Adds extra IPC complexity. Rejected.
- Sharded gateway: Not needed at MVP scale (2–10 bots, each low-traffic).

---

## 4. google-adk LlmAgent Pattern

**Decision:** Use `google.adk.agents.LlmAgent` with two registered tool functions: `memory_search` (EMOS RRF search + BM25 rerank) and `emit_citations` (inline `memory_url` link construction). The agent is instantiated once per agent at process startup with an agent-specific system prompt. Each DM turn is dispatched via `await orchestrator.run_async(message, user_id=discord_user_id)`.

**Rationale:** The existing `agent_factory.py` and `orchestrator.py` already implement this pattern for the prior Matrix runtime. `LlmAgent` handles the Gemini function-calling loop; tools are Python callables decorated with `@adk.tool`. The agent-scoped system prompt enforces the persona contract and the evidence-only response rule. The `orchestrator.py` already has the multi-turn context window logic that can be adapted.

**Alternatives considered:**
- Raw `genai.GenerativeModel.generate_content` without ADK: Requires manually implementing the function-calling loop and tool dispatch. Rejected — ADK already handles this correctly.
- LangChain: Not in the project stack. Rejected.

---

## 5. Transcript Batch Grouping Rules

**Decision:** Group adjacent `Segment` rows from the same `Source` into `TranscriptBatch` records using:

1. **Silence gap** (primary): If `next_segment.start_ms - current_segment.end_ms > 3_000`, start a new batch.
2. **Character limit** (secondary): If adding the next segment would make the accumulated batch text exceed **1,800 characters**, start a new batch.
3. **Speaker change** (tertiary, optional): If both segments have a non-null `speaker` field and they differ, start a new batch.

The `batch_rule` column records the trigger (`"silence_gap"`, `"char_limit"`, or `"speaker_change"`). When segments lack `start_ms`/`end_ms` (uncommon for YouTube transcripts), fall back to character-limit-only grouping.

**Rationale:** 3 s is the standard paragraph-boundary heuristic for auto-captioned speech. The 1,800-char ceiling keeps each Discord batch message reliably under Discord's 2,000-char per-message limit with headroom for speaker labels or timestamps. These thresholds are soft defaults, tunable via agent/subscription config. DESIGN.md explicitly forbids EMOS MemCell summaries in feed posts; batches use only verbatim segment text.

**Alternatives considered:**
- Fixed N-segment batches: Ignores natural speech cadence. Rejected.
- EMOS MemCell grouping: Explicitly forbidden by DESIGN.md. Rejected.

---

## 6. Memory URL Shape and Citation Model

**Decision:** Memory URLs follow the pattern `https://www.bibliotalk.space/memories/{user_id}_{YYYYMMDDTHHMMSSZ}` where the timestamp is the EverMemOS MemCell `timestamp` (UTC, compact). The `Evidence` Pydantic model includes `memory_url`, `memory_user_id`, `memory_timestamp` fields, fully derivable from EMOS retrieval/search response fields — no extra API call required.

The existing `Citation.index: int` field and citation-index-based validation are removed. `validate_citations` is replaced with `validate_evidence_links` which checks:
1. `memory_user_id == agent_slug` (cross-agent isolation)
2. The `(memory_user_id, memory_timestamp)` pair appears in the current retrieval result set (not stale from a prior turn)
3. Any `quote_snippet` in the response text is a substring of the corresponding cached `segment.text`

**Rationale:** DESIGN.md specifies inline markdown links as the only citation format. The `memory_url` is fully constructible from `user_id` + `timestamp` returned by EMOS without a secondary lookup.

**Alternatives considered:**
- Separate citation resolution API call per link: Unnecessary round-trip. Rejected.
- Bracketed indices `[1]` + `Sources:` trailing block: Explicitly forbidden by FR-025. Rejected.

---

## 7. Existing Code Reuse Summary

| Component                                          | Disposition    | Notes                                                                         |
| -------------------------------------------------- | -------------- | ----------------------------------------------------------------------------- |
| `memory_service/pipeline/chunking.py`           | Keep unchanged | 1,200-char sentence-aware chunking matches FR-003 exactly                     |
| `memory_service/adapters/youtube_transcript.py` | Adapt (minor)  | Remove non-YouTube metadata fields; keep transcript fetch + yt-dlp shell-out  |
| `memory_service/adapters/rss_feed.py`           | Keep           | Wire as FR-015 optional fallback                                              |
| `memory_service/pipeline/ingest.py`             | Adapt          | Replace `index.py` SQLite client with `AsyncSession` calls                    |
| `memory_service/pipeline/index.py`              | Adapt          | Replace raw `sqlite3` with SQLAlchemy ORM reads/writes                        |
| `agents_service/agent/tools/memory_search.py`      | Adapt          | Agent-scoped `user_id`; import updated `Evidence`                             |
| `agents_service/agent/tools/emit_citations.py`     | Adapt          | Drop index field; emit inline `[text](memory_url)` Markdown                   |
| `services/agents_service/src/models/citation.py` | Rebuild        | New `Evidence` shape; remove `Citation.index`; add `memory_url` fields        |
| `services/agents_service/src/models/segment.py`  | Keep unchanged | `Segment` + `bm25_rerank` reused directly                                     |
| `agents_service/agent/providers/gemini.py`         | Keep           | Gemini LLM provider                                                           |
| `agents_service/agent/agent_factory.py`            | Adapt          | Updated system prompt; new `Evidence` model wired                             |
| `agents_service/agent/orchestrator.py`             | Adapt          | Discord DM context replaces Matrix room context                               |
| `packages/bt_common/src/evermemos_client.py`       | Keep unchanged | `search`, `memorize`, `delete_by_group_id`                                    |
| `agents_service/matrix/`                           | **DELETE**     | Matrix transport — out of scope                                               |
| `agents_service/voice/`                            | **DELETE**     | Voice pipeline — out of scope                                                 |
| `agents_service/admin/`                            | **DELETE**     | SQLAdmin UI — out of scope                                                    |
| `agents_service/agent/providers/aws_nova.py`       | **DELETE**     | Non-Gemini provider                                                           |
| `agents_service/database/`                         | **DELETE**     | Old SQLAlchemy schema; replaced by the shared schema in `packages/bt_store/` |
| `agents_service/server.py`                         | **DELETE**     | Litestar HTTP server — not needed                                             |
| `memory_service/adapters/blog_crawl.py`         | **DELETE**     | Non-YouTube                                                                   |
| `memory_service/adapters/document.py`           | **DELETE**     | Non-YouTube                                                                   |
| `memory_service/adapters/gutenberg.py`          | **DELETE**     | Non-YouTube                                                                   |
| `memory_service/adapters/http_fetch.py`         | **DELETE**     | Non-YouTube                                                                   |
| `memory_service/adapters/local_text.py`         | **DELETE**     | Non-YouTube                                                                   |
| `memory_service/adapters/url_tools.py`          | **DELETE**     | Non-YouTube utilities                                                         |
| `memory_service/adapters/web_page.py`           | **DELETE**     | Non-YouTube                                                                   |
| `memory_service/server.py`                      | **DELETE**     | FastAPI HTTP server — not needed                                              |
| `memory_service/pipeline/manifest.py`           | **DELETE**     | Manifest batch ingest — not MVP                                               |
