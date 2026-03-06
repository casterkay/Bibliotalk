# Bibliotalk (諸子云) System Design

## Vision

Bibliotalk is a social network where every account — whether a living person, a public figure, or a historical figure like Aristotle — has an AI "Ghost" built from their real-world public digital footprint (podcast transcripts, YouTube talks, books, social posts). Users interact with each other and with Ghosts on a Matrix-based platform via Element.

**Core principle: 言必有據** — every Ghost utterance must be faithfully grounded in its collected personal memory (EverMemOS), with verifiable citations.

## Authoritative Implementation Notes (Current Code)

The repository file structure is authoritative for module ownership and import boundaries.

- `services/agents_service/src/matrix/appservice.py` is the single owner of `format_ghost_response`.
- Citation and segment domain models are owned by `services/agents_service/src/models/`.
- Agent runtime code is under `services/agents_service/src/agent/`.
- `packages/bt_common/src/` is infra-only (`evermemos_client`, `config`, `logging`, `exceptions`).
- `services/ingestion_service/src/` is layered as:
  - `domain/` (models, ids, errors)
  - `pipeline/` (chunking, manifest, ingest, index)
  - `runtime/` (config, reporting)
  - `adapters/` (local/gutenberg/youtube source loaders)

If any section below conflicts with the current tree, follow the tree.

### Rules

1. **Public content originates from real humans only.** Profile rooms display aggregated real-world content. Ghosts cannot post or comment in public rooms.
2. **Private chats allow Ghosts.** Users create private rooms and specify which participants are real users (requires invitation acceptance) or Ghosts.
3. **Ghosts must cite sources.** Every non-trivial factual claim by a Ghost must reference an evidence record from its EverMemOS memory. If no evidence exists, the Ghost must say so.

### Scope

**MVP:**
- Matrix + Element as the sole UI (no web portal)
- Self-hosted Synapse with appservice for Ghost virtual users
- Figure Ghosts with platform-managed ingestion (Podwise podcasts, Project Gutenberg, YouTube transcripts)
- User Ghosts powered by user-provided EverMemOS API keys
- Private text chat with Ghosts (1:1 and group)
- Multi-agent discussion rooms ("agentic podcasts") via an in-process orchestrator (Matrix-native); optional remote-runner adapter later
- Voice calls via MatrixRTC with JS sidecar (Nova Sonic / Gemini Live)
- Google ADK agent framework with swappable LLM (Gemini API / Nova Lite v2)

**Deferred:**
- Social media ingestion (X, Threads, Reddit) + Nova Act browser automation
- Billing / token metering
- Federation with external Matrix homeservers

---

## 1. Service Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Element Clients                        │
│          (Web, Desktop, Mobile — only UI)                │
└──────────────────────┬──────────────────────────────────┘
                       │ Matrix Client-Server API
┌──────────────────────▼──────────────────────────────────┐
│              Synapse (self-hosted)                        │
│         Matrix homeserver on ECS/EC2                      │
│                       │                                   │
│         Appservice HTTP push (PUT /transactions)          │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────▼─────────────┐
          │    agents_service        │
          │  (Python — Litestar)     │
          │                          │
          │  ┌────────────────────┐  │
          │  │ Appservice Handler │  │  ← receives all Matrix events
          │  │ (matrix)           │  │  ← sends as virtual users (@bt_*)
          │  └────────┬───────────┘  │
          │           │              │
          │  ┌────────▼───────────┐  │
          │  │ Agent Orchestrator │  │  ← Google ADK (LlmAgent, LoopAgent)
          │  │                    │  │  ← per-Ghost ADK runner (optional remote-runner adapter)
          │  │ Tools:             │  │
          │  │  memory_search     │  │  → EverMemOS retrieve
          │  │  emit_citations    │  │  → post citations to Matrix
          │  └────────┬───────────┘  │
          │           │              │
          │  ┌────────▼───────────┐  │
          │  │ Voice Bridge       │  │  ← communicates with JS sidecar
          │  │ (audio routing)    │  │     via WebSocket/IPC
          │  └────────────────────┘  │
          └──────────────────────────┘
                       │
          ┌────────────▼─────────────┐
          │  voice_call_service      │
          │  (Node.js)               │
          │                          │
          │  MatrixRTC client        │  ← joins Element Call sessions
          │  WebRTC media handling   │  ← audio encode/decode
          │  Audio bridge to Python  │  ← WebSocket/IPC to agents_service
          └──────────────────────────┘

          ┌──────────────────────────┐
          │   ingestion_service      │
          │  (Python — async)        │
          │                          │
          │  Podwise ingestion        │  → podcasts → EMOS + profile room
          │  Gutenberg ingestion     │  → books → EMOS + profile room
          │  YouTube ingestion       │  → transcripts → EMOS + profile room
          │  Scheduled jobs          │
          └──────────────────────────┘

          ┌──────────────────────────┐
          │  Relational DB (SQL)     │  ← agents, sources/segments,
          │  SQLite (local)          │     rooms, chat_history, configs
          │  Postgres (prod)         │
          └──────────────────────────┘

          ┌──────────────────────────┐
          │  EverMemOS (managed)     │  ← platform instance (figures)
          │                          │  ← user-provided instances (users)
          └──────────────────────────┘
```

### agents_service

The core service. Runs as a Synapse appservice and hosts the agent runtime.

- **Appservice handler**: Receives Matrix events and emits Ghost responses.
- **Message formatter**: `format_ghost_response` is defined in `matrix/appservice.py` and reused by CLI and voice transcript paths.
- **Agent runtime**: lives in `agent/` (`agent_factory.py`, `orchestrator.py`, `tools/`, `providers/`).
- **Agent domain models**: citation and segment models live in `models/`.
- **Voice bridge**: Coordinates with the JS sidecar for MatrixRTC voice sessions. Routes audio between the sidecar and LLM voice backends (Nova Sonic / Gemini Live).

### voice_call_service

Node.js process that handles MatrixRTC/WebRTC media.

- Joins Element Call sessions as a Ghost's virtual user
- Handles WebRTC signaling, Opus decode/encode, PCM resampling
- Bridges audio to agents_service via local WebSocket or IPC:
  - Sends user audio (PCM 16kHz) to agents_service
  - Receives Ghost audio (PCM 24kHz from Nova Sonic, or Gemini Live output) from agents_service
- One sidecar process can handle multiple concurrent voice sessions

### ingestion_service

Background job processor for figure content ingestion.

- `domain/`: core ids, models, and typed errors.
- `pipeline/`: manifest parsing/resolution, chunking, ingest pipeline, and index.
- `runtime/`: environment config and reporting/redaction.
- `adapters/`: source loaders (local text, Gutenberg, YouTube transcripts).
- Polls for new content on schedule (new podcast episodes, etc.)
- Ingests into EverMemOS via memorize API
- Posts content threads to figure profile rooms via appservice API
- Tracks progress in `ingestion_jobs` table

### bt_common (shared Python library, in-repo package)

Shared code used by both agents_service and ingestion_service:

- **EMOS client**: Async httpx client for `/api/v1/memories` endpoints (memorize, search, conversation-meta)
- **Config**: shared environment settings and EMOS fallback helpers
- **Logging**: structured JSON logging and correlation IDs
- **Exceptions**: shared infra/domain exception base types

---

## 2. Identity Model

### Accounts

| Type       | Description                                           | Ghost Name                               | Memory Source                              |
| ---------- | ----------------------------------------------------- | ---------------------------------------- | ------------------------------------------ |
| **Figure** | Platform-managed. Public figures, historical figures. | "Confucius (Ghost)", "Elon Musk (Ghost)" | Platform EMOS instance (platform-ingested) |
| **User**   | Real human on the platform. Registers via Matrix.     | "Alice (Ghost)"                          | User-provided EMOS API key                 |

### Matrix Users

Every Matrix account on the Bibliotalk homeserver is either a real user or a Ghost virtual user:

- **Real users**: `@alice:bibliotalk.space` — registered normally via Element
- **Ghost virtual users**: `@bt_ghost_alice:bibliotalk.space` — created by the appservice when user joins or when a figure is configured

The appservice reserves the `@bt_*` namespace. Synapse routes all events involving these users to agents_service.

### Appservice Registration (YAML)

```yaml
id: bibliotalk
url: "http://agents-service:8009"
as_token: <generated>
hs_token: <generated>
sender_localpart: bt_system
namespaces:
  users:
    - exclusive: true
      regex: "@bt_.*"
  aliases:
    - exclusive: true
      regex: "#bt_.*"
rate_limited: false
```

---

## 3. Data Model (Relational SQL; Postgres dialect)

> Implementation note (2026-03-06):
> The relational schema below is the *logical* data model. The codebase accesses it via
> SQLAlchemy ORM.
> - Local end-to-end development uses **SQLite** (async `aiosqlite` driver).
> - Production targets **Postgres** (self-hosted or managed), using the same ORM models.

### agents

```sql
create table agents (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('figure', 'user')),
  display_name text not null,           -- "Confucius (Ghost)"
  matrix_user_id text not null unique,  -- "@bt_ghost_confucius:bibliotalk.space"
  avatar_url text,
  bio text,
  persona_prompt text not null,         -- system prompt for this Ghost
  llm_model text not null default 'gemini-2.5-flash',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
```

### agent_emos_config

```sql
create table agent_emos_config (
  agent_id uuid primary key references agents(id),
  emos_base_url text not null,          -- platform URL for figures, user-provided for users
  emos_api_key_encrypted text,          -- encrypted; null if platform instance uses service auth
  tenant_prefix text not null           -- "{agent_id}" for figures; user-configured for users
);
```

### users

```sql
create table users (
  id uuid primary key default gen_random_uuid(),
  matrix_user_id text not null unique,  -- "@alice:bibliotalk.space"
  display_name text not null,
  agent_id uuid references agents(id),  -- their Ghost
  created_at timestamptz not null default now()
);
```

### figures

```sql
create table figures (
  agent_id uuid primary key references agents(id),
  canonical_name text not null,         -- "Confucius"
  aliases text[] not null default '{}',
  language_default text not null default 'en',
  sources_config jsonb not null default '{}'
  -- e.g. {"podwise": {"search_terms": ["Lex Fridman"], "max_episodes": 200},
  --       "gutenberg": {"book_ids": [1342]},
  --       "youtube": {"channel_ids": ["UC..."], "playlist_ids": ["PL..."]}}
);
```

### profile_rooms

```sql
create table profile_rooms (
  agent_id uuid primary key references agents(id),
  matrix_room_id text not null unique,  -- "!abc123:bibliotalk.space"
  created_at timestamptz not null default now()
);
```

### sources (upstream content items: episodes, books, videos)

```sql
create table sources (
  id uuid primary key default gen_random_uuid(),
  agent_id uuid not null references agents(id),
  platform text not null check (platform in ('podwise', 'gutenberg', 'youtube')),
  external_id text not null,            -- episode UUID, Gutenberg book ID, YouTube video ID
  external_url text,                    -- canonical URL to original content
  title text not null,
  author text,
  published_at timestamptz,
  raw_meta jsonb,                       -- platform-specific metadata (speaker list, chapter count, etc.)
  emos_group_id text not null unique,   -- "{agent_id}:{platform}:{external_id}" — shared by all segments from this source
  created_at timestamptz not null default now(),
  unique (platform, external_id)
);
```

### segments (canonical chunks — used for EMOS memorize, profile room posts, and citation validation)

```sql
create table segments (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id),
  agent_id uuid not null references agents(id),
  platform text not null,               -- denormalized from source for fast queries
  seq int not null,                     -- chunk index within source
  text text not null,                   -- canonical chunk text (verbatim)
  speaker text,                         -- speaker label (for conversations)
  start_ms int,                         -- start timecode in milliseconds
  end_ms int,                           -- end timecode in milliseconds
  sha256 text not null,                 -- content hash for dedup
  emos_message_id text not null unique, -- unique per segment: "{agent_id}:{platform}:{external_id}:seg:{seq}"
  matrix_event_id text,                 -- event ID of the profile room post (null if not yet posted)
  created_at timestamptz not null default now(),
  unique (source_id, seq)
);
```

The `segments` table serves three purposes:
1. **Ingestion dedup**: Check `sha256` or `(source_id, seq)` before re-ingesting.
2. **Citation validation**: Look up `segments.text` locally to verify a citation's `quote` is a substring, without hitting EMOS.
3. **Profile room posting**: Track which segments have been posted via `matrix_event_id`.

**EMOS ↔ relational mapping**: EMOS search returns memories with `group_id`. Map `group_id` → `sources.emos_group_id` → `segments` (via `source_id`). Then do a local re-rank (BM25 on `segments.text`) to find the most relevant segment(s) within the matched source. This is necessary because EMOS returns extracted *summaries*, not original verbatim content.

### ingestion_jobs

```sql
create table ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  agent_id uuid not null references agents(id),
  platform text not null check (platform in ('podwise', 'gutenberg', 'youtube')),
  status text not null default 'pending' check (status in ('pending', 'running', 'done', 'failed')),
  cursor jsonb,                         -- progress tracking (last processed item, etc.)
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

### chat_history (private chat and voice call transcripts — for history and audit)

```sql
create table chat_history (
  id uuid primary key default gen_random_uuid(),
  matrix_room_id text not null,
  sender_agent_id uuid references agents(id),  -- null if sent by real user
  sender_matrix_user_id text not null,
  matrix_event_id text,                         -- null for voice turns (no Matrix event)
  modality text not null default 'text' check (modality in ('text', 'voice')),
  content text not null,                        -- text message or voice transcript
  citations jsonb not null default '[]',        -- structured citation objects
  created_at timestamptz not null default now()
);
```

For voice calls, each Ghost turn is transcribed (Nova Sonic / Gemini Live provide transcripts as `Transcript` events) and stored with `modality = 'voice'`. This enables:
- Audit trail of what was said in voice calls
- Future memorization into EMOS (Ghost remembers past conversations)
- Users asking "what did Confucius say in our call?"

---

## 4. EverMemOS Integration

### Configuration

| Setting                 | Value                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------- |
| Platform EMOS (figures) | Single managed instance; agents_service and ingestion_service share credentials        |
| User EMOS (users)       | User-provided `emos_base_url` + `emos_api_key` stored encrypted in `agent_emos_config` |

### EMOS HTTP Headers

All requests to the managed EMOS instance include:
- `Authorization: Bearer {emos_api_key}` (if required)

### API Usage

All EMOS endpoints are under `/api/v1/memories`.

| Endpoint                      | Method | Use Case                                                                                                                                |
| ----------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `/memories`                   | POST   | **Memorize**: store each segment as a message. Fields: `message_id`, `sender`, `content`, `group_id`, `group_name`, `role="assistant"`. |
| `/memories/conversation-meta` | POST   | **Set group metadata**: call once per source to set `scene_desc`, `user_details`, `tags` with platform/source metadata.                 |
| `/memories/search`            | GET    | **Retrieve**: search with `retrieve_method="rrf"`, `top_k=8`. Use `retrieve_method="agentic"` when RRF results are insufficient.        |

### Tenant ID Convention

```
sender    = "{agent_id}"
            (same across all platforms — one EMOS user per agent)

group_id  = "{agent_id}:{platform}:{external_id}"
            e.g. "a1b2c3:podwise:episode_abc123"
            e.g. "a1b2c3:gutenberg:book_1342"
            e.g. "a1b2c3:youtube:video_dQw4w9WgXcQ"

message_id = "{agent_id}:{platform}:{external_id}:seg:{seq}"
            (unique per segment within a source)
```

- `sender` / `user_id` = the agent's Postgres UUID. Same across all platforms so that `GET /memories/search?user_id={agent_id}` returns all memories for this agent regardless of source.
- `group_id` = per source item (one episode / one book / one video). All segments from the same source share a `group_id`. This gives EMOS cross-segment context for better memory extraction.
- `message_id` = per segment (unique). Maps 1:1 to `segments.emos_message_id` in the relational DB.

For platform-managed figures, `agent_id` is the Postgres UUID. For user agents, the user configures their `tenant_prefix` in `agent_emos_config` to match their EMOS setup.

---

## 5. Agent Framework (Google ADK)

### Ghost Agent Definition

Each Ghost is an ADK `LlmAgent`:

```python
from google.adk.agents import LlmAgent

def create_ghost_agent(agent_row, emos_config) -> LlmAgent:
    return LlmAgent(
        name=f"ghost_{agent_row.id}",
        description=agent_row.bio or agent_row.display_name,
        model=agent_row.llm_model,  # "gemini-2.5-flash" or "amazon.nova-lite-v2:0"
        instruction=build_persona_instruction(agent_row),
        tools=[
            memory_search,      # EMOS retrieve → evidence list
            emit_citations,     # post citations to Matrix room
        ],
    )
```

### Persona Instruction Template

```
You are {display_name}, a Ghost (digital twin) on Bibliotalk.

{persona_prompt}

## Rules (言必有據)
- Before answering any factual question, call memory_search to retrieve relevant evidence.
- Ground every claim in retrieved evidence. Cite sources using superscript markers: ¹, ², ³, etc.
- After your response, call emit_citations with the structured citation objects.
- If no relevant evidence exists, say: "I don't have evidence in my memory for that."
- Never fabricate quotes, events, or opinions not supported by your memory.

## Output Format
Respond naturally in conversation. Use superscript numbers (¹²³) inline for citations.
```

### Tools

```python
async def memory_search(query: str, top_k: int = 8) -> list[Evidence]:
    """Search the Ghost's EverMemOS memory for relevant evidence.

    Strategy: Try RRF search first (fast). If results are insufficient
    (few results or low scores), retry with retrieve_method="agentic"
    for LLM-guided multi-round retrieval.

    EMOS returns extracted *summaries*, not original content. To get
    verbatim text for citations, we map group_ids → sources → segments.
    """
    # Step 1: RRF search
    result = await evermemos_client.search(
        query=query,
        user_id=agent_id,          # same across all platforms
        retrieve_method="rrf",
        memory_types=["episodic_memory"],
        top_k=top_k,
    )
    # result.memories = [{"episodic_memory": [{"summary": "...", "group_id": "..."}]}]

    group_ids = extract_group_ids(result.memories)

    if len(group_ids) < 3:
        # Step 2: Agentic retrieval (LLM-guided multi-round)
        result = await evermemos_client.search(
            query=query,
            user_id=agent_id,
            retrieve_method="agentic",
            memory_types=["episodic_memory"],
            top_k=top_k,
        )
        group_ids = extract_group_ids(result.memories)

    # Step 3: Map EMOS group_ids → sources → segments for verbatim text
    sources = await store.fetch_sources_by_emos_group_ids(group_ids)
    all_segments = await store.fetch_segments_by_source_ids(
        [s.id for s in sources]
    )

    # Step 4: Local re-rank — find most relevant segments within matched sources
    ranked = local_bm25_rerank(query, all_segments, top_k=top_k)

    return [Evidence(
        segment_id=seg.id,
        emos_message_id=seg.emos_message_id,
        source_title=seg.source.title,
        source_url=seg.source.external_url,
        text=seg.text,
        platform=seg.platform,
    ) for seg in ranked]

async def emit_citations(citations: list[Citation]) -> str:
    """Emit structured citations — included in the Ghost's response message.

    The citations are embedded in the Matrix event's com.bibliotalk.citations
    field and rendered as an HTML footer. This tool signals the framework to
    attach citations to the current response rather than posting a separate message.
    """
    return "Citations attached to response."
```

### LLM Backend Swapping

ADK resolves models via `LLMRegistry`. Register Nova Lite v2 as a custom backend:

```python
from google.adk.models import LLMRegistry, BaseLlm

class NovaLiteBackend(BaseLlm):
    """AWS Nova Lite v2 via Bedrock Converse API."""
    async def generate_content(self, request):
        response = await bedrock_converse(
            model_id="amazon.nova-lite-v2:0",
            system=request.system_instruction,
            messages=request.messages,
            tools=request.tools,
        )
        return convert_to_adk_response(response)

LLMRegistry.register("amazon.nova-lite-v2:0", NovaLiteBackend)
```

Agents default to `gemini-2.5-flash` (ADK built-in). Per-agent override via `agents.llm_model` column.

---

## 6. Multi-Agent Discussions (Streaming + Floor Control)

Multi-agent rooms are live chats: participants (users and Ghosts) stream text and/or voice in real time. The system must enforce **at most one speaker at a time**, support **user barge-in** (user can interrupt anytime), and still let Ghosts **autonomously request the floor** (including agent↔agent interruption), without creating reply storms or feedback loops.

### Architecture (single authority, Matrix-native)

In MVP, orchestration is centralized in `agents_service` per room (single authority). Matrix is the only shared transcript, but Ghosts do **not** autonomously “reply to whatever they see” by posting directly. Instead:

- Ghost runners observe the room timeline and submit `REQUEST_FLOOR` intents to the controller.
- A per-room **Discussion Controller** grants the floor to exactly one speaker, streams that speaker’s output to Matrix and/or the call, and can cancel an in-flight stream instantly.

If/when Ghosts become separately deployed services (or third-party plugins), keep the controller contract and add a remote-runner adapter at the runner boundary (optional).

```
Room timeline (Matrix events + voice ASR/VAD)
                    │
                    ▼
         ┌──────────────────────┐
         │ Discussion Controller │  (authoritative)
         │  - Event Normalizer   │
         │  - Floor Manager      │
         │  - Scheduler          │
         │  - Stream Router      │
         └──┬────────┬──────────┘
            │        │
   invoke   │        │  post/stream
            ▼        ▼
        Ghost Runner   Matrix room + Element Call
        (ADK agent)
```

### Unified event model

Normalize all inputs into a single internal stream of `UtteranceEvent`s:

- Matrix: `m.room.message` (text), edits (streaming text), reactions (optional)
- Voice: VAD start/end + ASR partial/final (from `voice_call_service`)

Each `UtteranceEvent` includes:
`room_id`, `event_id`, `speaker_id`, `is_user`, `modality` (`text|voice`), `phase` (`partial|final`), `ts`, `content`, and `addressed_agents` (derived from explicit mentions / name matching, primarily from **user** utterances).

### Floor manager (authoritative state machine)

The Floor Manager is the only source of truth for “who may speak now”:

- States:
  - `IDLE`
  - `USER_SPEAKING(user_id)`
  - `AGENT_SPEAKING(agent_id, generation_id)`

- User barge-in (absolute priority):
  - On user VAD start or user text send: immediately `CANCEL(generation_id)` if an agent is speaking, stop streaming output, transition to `USER_SPEAKING`.

- Release:
  - On user end-of-utterance (VAD end + short silence threshold) → `IDLE`
  - On agent stream completion / timeout / cancel → `IDLE`

Cancellation is a first-class primitive: every agent generation (text stream and/or voice TTS) runs with a cancellation token keyed by `generation_id` and must stop promptly when cancelled.

### `REQUEST_FLOOR` (agent intent API)

Agents never post directly; they submit/update a single outstanding request per room (agent-provided `urgency`/`relevance` are advisory; the controller may recompute scores from context):

```json
{
  "type": "REQUEST_FLOOR",
  "room_id": "!abc:server",
  "agent_id": "@bt_ghost_confucius:bibliotalk.space",
  "force": false,
  "reason": "Answer the user's question about virtue ethics.",
  "urgency": 0.6,
  "relevance": 0.8,
  "estimate_ms": 12000,
  "max_tokens": 500
}
```

Rules:

- `force=true` means “interrupt the current **agent** speaker and take the floor now”.
- Agents may submit `REQUEST_FLOOR` while the user is speaking, but **must** use `force=false`.
- The controller may clamp `max_tokens`/`estimate_ms` (especially for `force=true`) and apply cooldowns to prevent thrash.

### Scheduling (who speaks next)

When the floor becomes available (`IDLE`), the Scheduler selects the next speaker from outstanding requests.

Selection is score-based with hard constraints:

- Hard constraints:
  - Never preempt `USER_SPEAKING`.
  - At most one agent speaks at a time.
  - Per-agent cooldown + max continuous speaking time.

- Score:
  - `score = w_m * mention_boost + w_r * relevance + w_u * urgency + w_f * fairness + w_e * evidence`
  - `mention_boost`: if the latest **user** utterance explicitly mentions an agent (Matrix mention, `@bt_ghost_*`, or reliable display-name match), that agent’s next turn is strongly preferred.
  - `relevance`: overall fit to the current conversational state (topic alignment, direct question answering, continuity); “topic coherence” is part of this.
  - `evidence`: preference for agents that can cite grounded memory for the asked question (e.g., they already found supporting segments in a preflight search).

Force handling:

- If `AGENT_SPEAKING(...)` and another agent submits `REQUEST_FLOOR(force=true)`:
  - The controller may grant it only if (a) user is not speaking, (b) the request clears a high threshold, and (c) interrupt rate limits allow it.
  - On grant, cancel the current agent stream and hand over the floor immediately.

### Streaming output (text)

When an agent is granted the floor, the Stream Router:

1. Posts a placeholder message as that agent (e.g., “…”).
2. Streams tokens by editing that message (Matrix edit events).
3. Finalizes the message when complete.
4. Posts citations either inline (preferred) or as a follow-up message/thread, validated by `validate_citations()`.

If cancelled (user barge-in or forced interruption), stop editing immediately.

### Streaming output (voice)

For Element Calls:

- `voice_call_service` joins as each Ghost virtual user, but only the **floor holder** is unmuted for TTS emission.
- On user VAD start:
  - Immediately mute any Ghost audio output, cancel TTS generation, and transition to `USER_SPEAKING`.
- While user is speaking, agents may continue to observe ASR partials and submit `REQUEST_FLOOR(force=false)` so they can respond quickly when the user stops.

Citations are posted to the room in real time (paired text thread) while voice is playing, or immediately after the utterance ends.

### Optional: remote runners (future)

If Ghost runners become remote services, keep the same controller semantics and replace the “invoke Ghost runner” call with a remote-runner adapter. Floor control, cancellation, scoring, and Matrix/voice streaming remain centralized so behavior stays deterministic.

---

## 7. Matrix Room Design

There are exactly two kinds of rooms. The distinction is structural and immutable — determined at creation time by room configuration (power levels, join rules, encryption). No custom state events or mutable "allow AI" flags.

### Profile Rooms (Public, Read-Only)

Each agent (figure or user) has one profile room. Created by the appservice when a figure is configured or a user joins.

- **Room name**: "Confucius (Ghost) — Profile"
- **Room alias**: `#bt_confucius_profile:bibliotalk.space`
- **Join rules**: `public` (anyone on the homeserver can join to "follow")
- **Power levels**: Ghost virtual user = 50 (can send messages), all other users = 0 (read-only). `events_default` = 50 so only the Ghost can post.
- **No AI responses here.** Enforced by Matrix room permissions (read-only for non-Ghost users). Only ingestion_service posts verbatim ingested content.
- **Content format**: Each ingested source → Matrix thread. Root message = source description. Replies = verbatim segments.

```
Thread root (posted by ingestion_service as the Ghost's virtual user):
  📎 New podcast episode: "StarTalk — The Nature of Time" (2024-12-15)
  https://example.com/episode/xyz

  Thread replies:
    [0:00–2:30] Neil deGrasse Tyson discusses the arrow of time...
    [2:30–5:15] Guest explains entropy in everyday terms...
    [5:15–8:00] ...
```

```
Thread root:
  📎 The Analects of Confucius — Book I: On Learning
  https://www.gutenberg.org/ebooks/3330

  Thread replies:
    [1.1] The Master said, "Is it not a pleasure to learn and practice..."
    [1.2] Master You said, "Those who are filial and respectful..."
    ...
```

```
Thread root:
  📎 YouTube: "Lex Fridman Podcast #123 — Guest Name" (2024-06-01)
  https://www.youtube.com/watch?v=abc123

  Thread replies:
    [0:00–3:15] Discussion about consciousness and AI...
    [3:15–6:30] Guest shares perspective on free will...
    ...
```

### Private Rooms (Ghosts Can Participate)

All other rooms — DMs, group chats, multi-agent discussions, voice calls — are private rooms where Ghosts can respond.

- **Created by**: A user, via Element's room creation UI or bot commands
- **Join rules**: `invite` (private)
- **Power levels**: All participants (users and Ghosts) = 50
- **Ghost behavior**: Ghosts respond when mentioned, when directly messaged (DM), or on their turn in a multi-agent discussion. The appservice checks: if a room is NOT in `profile_rooms`, Ghosts are allowed to respond.
- **Voice**: Any private room can host an Element Call. Ghost virtual users join the call via voice_call_service. A text thread is created in the room for live transcripts + citations.

---

## 8. Ingestion Pipelines (Figures Only)

### Common Flow

```
Source API → Fetch metadata → Upsert sources row
         → Fetch content → Chunk → Dedupe (sha256) → Upsert segments rows
         → EMOS V3 memorize (per new/changed segment)
         → Post thread to profile room (root = source description, replies = segments)
         → Update segments.matrix_event_id
```

All ingestion runs in ingestion_service. Progress tracked in `ingestion_jobs`. Content metadata stored in `sources`, canonical chunks in `segments`.

### 8.1 Podwise (Podcasts)

**Method**: Playwright-based crawling of podcast transcripts on `https://podwise.ai`. No API keys required — transcripts are scraped from the public Podwise web interface.

**Figure config** (in `figures.sources_config`):
```json
{
  "podwise": {
    "search_terms": ["Neil deGrasse Tyson"],
    "max_episodes_per_term": 200
  }
}
```

**Algorithm**:
1. For each search term: use Playwright to search `podwise.ai` for matching podcast episodes with available transcripts.
2. For each episode: crawl the episode transcript page to extract transcript segments (text, speaker labels, timecodes).
3. Upsert `sources` row with `emos_group_id = "{agent_id}:podwise:{episode_id}"`.
4. Chunk into segments (~800-1200 chars, preserving speaker labels and timecodes).
5. Upsert `segments` rows with `emos_message_id = "{agent_id}:podwise:{episode_id}:seg:{seq}"`.
6. Set conversation metadata once per episode: `POST /memories/conversation-meta` with `group_id`, `scene_desc.extra` = `{platform, source_url, title, speakers}`.
7. For each new segment: `POST /memories` with:
   - `message_id` = `segments.emos_message_id`
   - `sender` = `"{agent_id}"` (no platform suffix)
   - `group_id` = `sources.emos_group_id`
   - `role` = `"assistant"`
   - `content` = segment text
8. Post thread to profile room (root = episode description, replies = segments).

**Dedup**: Track processed episodes in `ingestion_jobs.cursor`. Re-run weekly; skip already-processed episodes.

**Rate limiting**: Respect `podwise.ai` by adding delays between page requests and limiting concurrent crawl sessions.

### 8.2 Project Gutenberg (Books)

**Metadata API**: Gutendex at `https://gutendex.com/books`.

**Figure config**:
```json
{
  "gutenberg": {
    "book_ids": [1342, 11],
    "language_filter": ["en"]
  }
}
```

**Algorithm**:
1. For each book_id: fetch Gutendex record, pick `text/plain; charset=utf-8` format URL.
2. Download full text. Strip Gutenberg header/footer boilerplate.
3. Upsert `sources` row with `emos_group_id = "{agent_id}:gutenberg:{book_id}"`.
4. Chunk: split on chapter headings when detectable; fallback fixed-size (~1500-2500 chars).
5. Upsert `segments` rows with `emos_message_id = "{agent_id}:gutenberg:{book_id}:seg:{seq}"`.
6. Set conversation metadata: `POST /memories/conversation-meta` with `group_id`, `scene_desc.extra` = `{platform, title, authors, gutenberg_id}`.
7. For each new segment: `POST /memories` with `message_id`, `sender = "{agent_id}"`, `group_id`, `role = "assistant"`, `content` = segment text.
8. Post thread to profile room (root = book title + description, replies = chapter chunks).

### 8.3 YouTube Transcripts

**Library**: `youtube-transcript-api` (Python package, no API key required).

**Figure config**:
```json
{
  "youtube": {
    "video_ids": ["dQw4w9WgXcQ"],
    "channel_handles": ["@lexfridman"],
    "playlist_ids": ["PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"]
  }
}
```

**Algorithm**:
1. For channel handles / playlists: resolve to video ID lists (via YouTube Data API v3 or `yt-dlp --flat-playlist`).
2. For each video ID: fetch transcript via `youtube-transcript-api`.
3. Upsert `sources` row with `emos_group_id = "{agent_id}:youtube:{video_id}"`.
4. Chunk into segments (~800-1200 chars, preserving timestamps).
5. Upsert `segments` rows with `emos_message_id = "{agent_id}:youtube:{video_id}:seg:{seq}"`.
6. Set conversation metadata: `POST /memories/conversation-meta` with `group_id`, `scene_desc.extra` = `{platform, title, channel, video_url}`.
7. For each new segment: `POST /memories` with `message_id`, `sender = "{agent_id}"`, `group_id`, `role = "assistant"`, `content` = segment text.
8. Post thread to profile room (root = video title + description, replies = transcript segments).

---

## 9. Citation System

### Citation Object

```json
{
  "citations": [
    {
      "index": 1,
      "segment_id": "uuid-of-segment",
      "emos_message_id": "a1b2c3:podwise:episode_xyz:seg:12",
      "source_title": "StarTalk — The Nature of Time",
      "source_url": "https://example.com/episode/xyz",
      "quote": "Time is not a dimension we move through; it moves through us.",
      "platform": "podwise",
      "timestamp": "2024-12-15"
    }
  ]
}
```

For YouTube citations, `source_url` includes a timestamp deep link:
`https://www.youtube.com/watch?v=abc123&t=195` (start_ms / 1000).

### Matrix Message Format

Ghost responses are sent as `m.room.message` events with both human-readable rendering and a machine-readable citation payload in the event content:

```json
{
  "msgtype": "m.text",
  "body": "The Master said that learning without reflection is labor lost[^1], while reflection without learning is perilous[^2].\n\n──────────\nSources:\n[1] The Analects, Book II (gutenberg:3330)\n[2] The Analects, Book XV (gutenberg:3330)",
  "format": "org.matrix.custom.html",
  "formatted_body": "The Master said that learning without reflection is labor lost<sup>[1]</sup>, while reflection without learning is perilous<sup>[2]</sup>.<br><hr><b>Sources:</b><br>[1] <i>The Analects</i>, Book II — <a href=\"https://www.gutenberg.org/ebooks/3330\">gutenberg:3330</a><br>[2] <i>The Analects</i>, Book XV — <a href=\"https://www.gutenberg.org/ebooks/3330\">gutenberg:3330</a>",
  "com.bibliotalk.citations": {
    "version": "1",
    "items": [
      {
        "index": 1,
        "segment_id": "...",
        "emos_message_id": "...",
        "source_title": "The Analects, Book II",
        "source_url": "https://www.gutenberg.org/ebooks/3330",
        "quote": "Learning without reflection is a waste; reflection without learning is dangerous.",
        "platform": "gutenberg"
      }
    ]
  }
}
```

- **Plain body**: `[^N]` markers for clients without HTML support.
- **HTML body**: `<sup>[N]</sup>` markers + footer with clickable source links.
- **Custom field**: `com.bibliotalk.citations` carries the structured citation array for programmatic access.

### Validation

Before posting any Ghost response:
1. Parse citation markers from response text.
2. Verify each cited `segment_id` exists in the `segments` table for this agent.
3. Verify each `quote` is a substring of `segments.text` for the corresponding segment.
4. Strip any citations that fail validation; log a warning.

---

## 10. Voice Architecture (MatrixRTC + Nova Sonic / Gemini Live)

### Components

```
Element Call (WebRTC)
       │
       │  MatrixRTC signaling + media
       │
┌──────▼───────────────────────────┐
│   voice_call_service (Node.js)   │
│                                   │
│  livekit-client or matrix-js-sdk  │  ← MatrixRTC participant
│  WebRTC media track handling      │
│  Opus decode → PCM 16kHz          │  ← user audio in
│  PCM 24kHz → Opus encode          │  ← Ghost audio out
│                                   │
│  WebSocket bridge ──────────────────── agents_service (Python)
└───────────────────────────────────┘

agents_service:
  ┌─────────────────────────────────┐
  │  Voice Session Manager          │
  │                                 │
  │  ┌─── VoiceBackend (ABC) ────┐  │
  │  │                           │  │
  │  │  NovaSonicBackend         │  │  ← Bedrock bidirectional stream
  │  │  - send_audio_chunk()     │  │  ← receive audio + tool calls
  │  │  - tool: memory_search    │  │
  │  │  - tool: emit_citations   │  │
  │  │                           │  │
  │  │  GeminiLiveBackend        │  │  ← Gemini Live API WebSocket
  │  │  - send_audio_chunk()     │  │  ← receive audio + tool calls
  │  │  - tool: memory_search    │  │
  │  │  - tool: emit_citations   │  │
  │  └───────────────────────────┘  │
  └─────────────────────────────────┘
```

### Voice Backend Interface

```python
from abc import ABC, abstractmethod

class VoiceBackend(ABC):
    @abstractmethod
    async def start_session(self, system_prompt: str, tools: list) -> None: ...

    @abstractmethod
    async def send_audio_chunk(self, pcm_16khz: bytes) -> None: ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[VoiceEvent]: ...
    # VoiceEvent = AudioChunk | ToolCall | Transcript | EndOfTurn

    @abstractmethod
    async def end_session(self) -> None: ...
```

### Nova Sonic Backend

Based on the [AWS Nova Sonic tool-use sample](https://github.com/aws-samples/amazon-nova-samples/blob/main/speech-to-speech/sample-codes/console-python/nova_sonic_tool_use.py):

- Model: `amazon.nova-sonic-v1:0`
- Region: `us-east-1`
- Bidirectional HTTP/2 stream via Bedrock Runtime
- Tools registered in session config: `memory_search`, `emit_citations`
- System prompt includes persona + grounding rules

### Gemini Live Backend

Based on the [Gemini Multimodal Live API](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api):

- WebSocket connection to Gemini Live endpoint
- Tools registered as function declarations
- Audio format: PCM 16kHz input, PCM 24kHz output (may vary; consult API docs)

### Multi-Agent Voice (Agentic Podcast)

For a discussion room with N Ghosts + 1 user in a voice call:

1. voice_call_service joins the call as N virtual users (one per Ghost).
2. Audio routing in agents_service:
   - Receive each participant's audio stream from the sidecar
   - For Ghost_i: mix all other participants' audio → feed to Ghost_i's voice backend
   - Ghost_i's output audio → send to sidecar → play as Ghost_i's virtual user in the call
3. Turn management via the orchestrator to prevent simultaneous speech.
4. Citations from each Ghost's `emit_citations` tool call → posted to paired text thread.
5. All voice transcripts (user and Ghost turns) stored in `chat_history` with `modality = 'voice'`.

---

## 11. Bot Commands (Matrix)

Implemented as Matrix room commands (messages starting with `!bt`).

| Command                                                   | Description                                                          |
| --------------------------------------------------------- | -------------------------------------------------------------------- |
| `!bt help`                                                | Show available commands                                              |
| `!bt ghost setup`                                         | Link your EMOS API key to activate your Ghost                        |
| `!bt ghost status`                                        | Show your Ghost's status and memory stats                            |
| `!bt ghost model <model>`                                 | Set your Ghost's LLM model (gemini-2.5-flash, amazon.nova-lite-v2:0) |
| `!bt discuss start <@ghost1> <@ghost2> [topic] [turns:N]` | Start a multi-agent discussion room                                  |
| `!bt discuss stop`                                        | End the current discussion                                           |
| `!bt call start <@ghost>`                                 | Start a voice call with a Ghost (must be in a voice-capable room)    |
| `!bt call stop`                                           | End the current voice call                                           |
| `!bt figure list`                                         | List all available figure Ghosts                                     |
| `!bt figure info <name>`                                  | Show a figure's profile and memory sources                           |
| `!bt admin figure create <name>`                          | (Admin) Create a new figure                                          |
| `!bt admin figure ingest <name> <source>`                 | (Admin) Trigger ingestion for a figure                               |
| `!bt admin jobs`                                          | (Admin) Show ingestion job status                                    |

---

## 12. Deployment (AWS)

### Infrastructure

| Component          | Deployment                                                                 |
| ------------------ | -------------------------------------------------------------------------- |
| Synapse            | ECS Fargate or EC2, with Postgres backend (RDS or self-hosted)             |
| agents_service     | ECS Fargate                                                                |
| voice_call_service | ECS Fargate (same task definition as agents_service, or sidecar container) |
| ingestion_service  | ECS Fargate                                                                |
| Postgres           | Managed (e.g., RDS) or self-hosted on ECS                                  |
| EverMemOS          | Managed cloud instance                                                     |

### Region

- voice_call_service and agents_service: **us-east-1** (Nova Sonic availability, Gemini Live latency)
- Synapse: same region for low-latency event delivery
- All other services: same region for simplicity

### Domain

- `bibliotalk.space` — Synapse homeserver
- Matrix user IDs: `@alice:bibliotalk.space`
- Ghost user IDs: `@bt_ghost_alice:bibliotalk.space`

---

## 13. Implementation Order

1. **Synapse + appservice scaffold**: Deploy Synapse, register appservice, verify virtual user creation
2. **Relational schema**: Create tables + migrations (SQLite local, Postgres prod), seed a test figure
3. **agents_service core**: Appservice event handler (matrix), basic message routing
4. **EMOS client**: Async Python client for `/api/v1/memories` (memorize, search, conversation-meta)
5. **ADK agent**: Ghost agent with persona instruction, memory_search tool, emit_citations tool
6. **Private text chat**: Ghost responds in DMs and group chats with grounded citations
7. **Ingestion — Podwise**: Podcast transcript ingestion pipeline + profile room threads
8. **Ingestion — Gutenberg**: Book text ingestion pipeline + profile room threads
9. **Ingestion — YouTube**: Transcript ingestion pipeline + profile room threads
10. **Multi-agent discussions**: LoopAgent orchestrator (in-process; optional remote-runner adapter later)
11. **voice_call_service**: MatrixRTC join, WebRTC audio handling, audio bridge to Python
12. **Voice backends**: Nova Sonic + Gemini Live implementations behind VoiceBackend ABC
13. **Voice calls**: End-to-end 1:1 voice call with a Ghost
14. **Multi-agent voice**: Audio mixing + orchestrated turn-taking for agentic podcasts

---

## 14. Key Dependencies

### Python (agents_service, ingestion_service)

```
litestar                    # ASGI framework for agents_service
google-adk                  # Agent Development Kit
google-genai                # Gemini API client
matrix                      # Matrix appservice framework
httpx                       # Async HTTP (EMOS)
playwright                  # Browser automation (Podwise crawling)
sqlalchemy                  # ORM (SQLite local; Postgres prod)
aiosqlite                   # Async SQLite driver (local dev)
alembic                     # Migrations (relational schema)
sqladmin                    # Admin UI (operates on SQLAlchemy models)
boto3                       # AWS Bedrock (Nova Sonic, Nova Lite)
youtube-transcript-api      # YouTube transcripts
pydantic                    # Data validation
pydantic-settings           # Env config
uvicorn                     # ASGI server (appservice HTTP endpoint)
```

### Node.js (voice_call_service)

```
matrix-js-sdk               # Matrix client (MatrixRTC signaling)
livekit-client              # Or direct WebRTC via MatrixRTC
werift                      # WebRTC implementation for Node.js (alternative)
ws                          # WebSocket (bridge to agents_service)
```

---

## 15. Security and Constraints

### Hard Rules (enforced)

1. **No AI in profile rooms.** Enforced by Matrix room permissions (profile rooms are read-only to non-Ghost users). Only ingestion_service posts verbatim segments.
2. **Citation validation.** Every Ghost response passes through `validate_citations()` before posting. Citations referencing nonexistent segments or mismatched quotes are stripped.
3. **Appservice namespace isolation.** Only `@bt_*` users are controlled by the appservice. Real users cannot impersonate Ghosts.

### Rate Limits

- Ghost responses: max 1 response per 5 seconds per room (prevent spam loops in multi-Ghost rooms).
- Ingestion: configurable per-platform rate limits to respect upstream API quotas.

### MVP Assumptions

- **Unencrypted call media.** Voice bots cannot participate in encrypted Element Call sessions. MVP voice calls are unencrypted. E2EE voice is deferred.
- **Single homeserver.** No federation in MVP. All users and Ghosts are on `bibliotalk.space`.
- **EMOS availability.** If the managed EMOS instance is down, Ghosts respond with "My memory is temporarily unavailable" rather than hallucinating.

### Secrets (AWS Secrets Manager)

```
SYNAPSE_SHARED_SECRET       # Synapse admin/registration
APPSERVICE_AS_TOKEN         # Appservice auth
APPSERVICE_HS_TOKEN         # Homeserver verification
PODWISE_BASE_URL            # Podwise crawl target (default: https://podwise.ai)
EMOS_BASE_URL               # Platform EMOS instance
EMOS_API_KEY
AWS_BEDROCK_REGION          # us-east-1
GOOGLE_API_KEY              # Gemini API
```

---

## 16. Testing

### Unit Tests

- **Chunking**: Podwise transcript, Gutenberg text, YouTube transcript chunking produces deterministic segments respecting size limits, preserving metadata (speaker, timecodes, chapter), and generating stable sha256 hashes.
- **EMOS ID builder**: Given agent_id + platform + external_id + seq, produces correct `emos_group_id` and `emos_message_id`.
- **Citation validation**: Rejects unknown `segment_id`; rejects `quote` not found as substring of `segments.text`; rejects cross-agent citation (segment belongs to different agent).
- **Matrix message renderer**: Produces correct HTML (`<sup>[N]</sup>`) + plain (`[^N]`) + `com.bibliotalk.citations` JSON for a given response + citations.
- **EMOS client**: Memorize and retrieve with correct tenant IDs, headers, and parameters.
- **ADK agent**: Mock LLM responses; verify tool calls (memory_search → emit_citations) and citation extraction.

### Integration Tests (with mocked external services)

- **Appservice**: Synapse pushes event → agents_service receives → Ghost responds in room with citations.
- **Ingestion end-to-end**: Podwise/Gutenberg/YouTube ingestor creates `sources` + `segments` rows, calls EMOS memorize, posts threads to profile room.
- **Citation round-trip**: Ingested segment → EMOS memorize → memory_search retrieves it → Ghost cites it → validation passes → posted with correct segment_id.
- **Multi-agent discussion**: Orchestrator invokes Ghost runners → Ghosts respond in turn → citations posted to shared room.
- **Profile rooms**: Verify non-Ghost users cannot send messages in profile rooms (Matrix permissions), and only ingestion_service posts verbatim segments.

### MVP "Done" Scenarios

1. Admin creates a figure (e.g., Confucius) with Gutenberg + Podwise sources. Ingestion populates `sources`, `segments`, EMOS. Profile room shows content threads with verbatim excerpts.
2. User joins homeserver. Ghost `User (Ghost)` is auto-created. User links their EMOS API key via `!bt ghost setup`.
3. User DMs `@bt_ghost_confucius`. Ghost responds with grounded citations — each citation's `quote` is verifiable as a substring of the referenced segment.
4. User creates a discussion room with Confucius and Aristotle Ghosts. Multi-turn discussion proceeds with grounded responses from both, each citing their own memories.
5. User starts a voice call with a Ghost. Ghost responds in voice (unencrypted Element Call). Citations appear in a text thread in the same room.
6. Switching voice engine (Nova Sonic ↔ Gemini Live) is a config toggle without changing higher-level call orchestration.
