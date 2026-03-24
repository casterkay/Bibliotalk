# Bibliotalk

**Steve Jobs'** dream comes true: talk with and learn from some of the greatest minds in human history, such as **Aristotle**.

Powered by **Gemini Live** and **EverMemOS**, Bibliotalk is a **Matrix** space where you can have real-time conversations with **AI Spirits** of famous human beings revived from their digital archives of *thoughts*, *talks*, *podcasts*, and so on. Every non-trivial claim they make is **evidence-based** with citations to original sources, to eliminate the notorious *"LLM hallucination"* issues.

Let's create your **world-class AI mentor group** in **Bibliotalk** now!

## The “wow” in one minute

- **Live voice chat** (Gemini Live streaming ASR/TTS + transcripts).
- **Grounded truth** (retrieval + citation validation outside the model; “no evidence” is allowed).
- **A real UX** (Element chat + Element Call; interruption and multi-turn feel native).

The key on-stage moment: *a Spirit speaks, then we click citations and show exact ingested excerpts that match the quote substrings*.

- **Chat in Element**: Spirits stream responses as you type; you can interrupt mid-answer and ask a new question.
- **Call in Element Call (1:1 MVP)**: talk naturally; a paired **transcript + citations** is posted back into the room.
- **Inspect the evidence**: citations point to exact ingested excerpts (verbatim), not vibes.
- **Browse the Archive**: public, read-only rooms that look like a living annotated book—per source, a deterministic summary root with verbatim excerpt replies.

Planned Spirits and primary sources: `ROSTER.md`.

## Built for

- **Learners** who want “teach me” *with receipts*.
- **Researchers** who need fast synthesis without losing provenance.
- **Teams** who want a voice interface over *their* corpus—without turning it into an untraceable soup.

## What makes Bibliotalk different

- **Citations are not decoration**: they’re validated against stored excerpts (quote-substring checks) and cannot cross Spirit boundaries.
- **Streaming-first UX**: text and voice are treated as live sessions, not “send message → wait → get blob”.
- **Archive and Dialogue are separate modes**: Archive Rooms never respond and never drift; Dialogue Rooms are interactive and can be interrupted.
- **Platform-agnostic core**: Matrix is the MVP UI; Discord is planned as a future adapter on the same contracts.

## What it looks like (illustrative)

```text
You: What does “virtue” mean here?
Spirit: In this text, “virtue” is treated as a kind of excellence of character… [1]

[1] Plato, Apology — cited excerpt (clickable in Element)
```

## Gemini Live, used the hard (and fun) way

Bibliotalk treats Gemini Live as a **real-time audio interface** (ASR/TTS + live transcription streams), while keeping truthfulness deterministic:

- Live provides **input/output transcripts** and natural voice.
- Bibliotalk’s agent core remains the **grounding authority**: retrieval, citation selection, and citation validation happen outside Live.
- The result is voice that stays fast *and* auditable: every spoken answer is mirrored as a cited text turn in the room.

## Trust model (how it stays honest)

1. **Ingest**: you choose sources (books, playlists, files). They’re chunked into canonical segments.
2. **Retrieve**: Spirits search their own memory first (EverMemOS + local rerank).
3. **Answer with proof**: the core agent emits plain text + structured citations; adapters format for Matrix/Discord.
4. **Verify**: citations are validated against stored segments; “no evidence” is a first-class outcome.

## Demo script (what to show on stage)

1. Ask a Spirit a non-trivial question in a Dialogue Room.
2. Interrupt mid-stream with a sharper follow-up (the Spirit cancels and pivots).
3. Click a citation and show the exact excerpt it was grounded on.
4. Start an Element Call, talk naturally, then point at the posted transcript + citations.

## Status

Matrix-first MVP is under active development; authoritative specs live in `specs/001-matrix-mvp/` and the system blueprint is `DESIGN.md`. Discord support may temporarily break during refactors, but remains a target platform.

## Roadmap (post-MVP)

- **Group calls + floor control** (who speaks when, active speaker policy).
- **Discord adapter parity** on the same core contracts.
- **Voice E2EE** (deferred for MVP).

---

## Developer Appendix

### Local Discord Voice Stack (Docker Compose)

Use this when developing `/voice join|status|leave` and Discord transcript posting locally.

1. Prepare env:
```bash
cp deploy/local/.env.example deploy/local/.env
```
Required values in `deploy/local/.env`:
- `DISCORD_TOKEN`
- `GOOGLE_API_KEY`
- `EMOS_BASE_URL`
- `EMOS_API_KEY`
- `BIBLIOTALK_AGENT`
- `DISCORD_COMMAND_GUILD_ID` (recommended for fast slash-command sync)
- `DISCORD_VOICE_DEFAULT_TEXT_CHANNEL_ID` (fallback transcript destination)

Compose defaults for in-container service routing:
- `VOIP_SERVICE_URL=http://voip:9012`
- `AGENTS_SERVICE_URL=http://agents:8009`

2. Start the stack:
```bash
docker compose -f deploy/local/docker-compose.yml up
```

This stack runs:
- `ingestion` (memory collector)
- `discord` (single Discord gateway client)
- `agents` (FastAPI `/v1/agents/*` + live WS)
- `voip` (Node 22 Gemini Live media bridge)
- `memories` (public memory pages/API)

3. Verify voice flow:
```bash
uv run --package bt_cli bibliotalk agent seed --help
```
Then in Discord:
- Run `/voice join` in your guild while connected to a voice channel.
- Speak and confirm audio round-trip.
- Confirm coalesced transcript updates in the configured text channel/thread.
- Run `/voice status` and verify saved guild-scoped binding is shown.
- Run `/voice leave`.

### Start a local Matrix stack (Synapse + Element + MatrixRTC)

```bash
./scripts/matrix-dev.sh provision
```

This brings up:
- Synapse (`http://localhost:8008`)
- Element Web (`http://localhost:8081`)
- Element Call (`http://localhost:9011`)
- LiveKit SFU (host ports `7880/tcp`, `7881/udp`, `50100-50200/udp`)
- `/.well-known/matrix/client` for MatrixRTC focus discovery (`http://localhost/.well-known/matrix/client`)

More details: `deploy/local/matrix/README.md`.

### Provision the demo Figure Rooms (Alan Watts + Steve Jobs)

```bash
uv run --package bt_cli bibliotalk matrix demo provision --figures alan-watts,steve-jobs
```

This creates/ensures the Bibliotalk Space + the two Figure Rooms and invites the Spirit virtual users
(`@bt_<agent_uuid>:localhost`) into their rooms.

### Local dev loop (Matrix MVP)

The end-to-end MVP loop (ingest → archive publish → dialogue chat → voice) is documented in: `specs/001-matrix-mvp/quickstart.md`.

### Canonical design docs

- Matrix MVP: `specs/001-matrix-mvp/spec.md`, `specs/001-matrix-mvp/plan.md`, `specs/001-matrix-mvp/contracts/`, `specs/001-matrix-mvp/quickstart.md`
- System blueprint: `DESIGN.md`
- Gemini Live notes: `docs/knowledge/gemini-live-api.md`

### Tech stack (current direction)

- Python 3.11+ services: ingestion + agent core (`fastapi`, `uvicorn`, `httpx`, `pydantic>=2`, `SQLAlchemy>=2`)
- Node.js services: Matrix adapter (`matrix-js-sdk`, Node 20+) + Discord `voip_service` media bridge (Node 22)
- EverMemOS for memory storage/retrieval; Gemini (ADK + Gemini Live) for reasoning + voice I/O

### Workspace commands

- Install deps: `UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras`
- Run tests (per package to avoid pytest root collisions):
  - `uv --directory services/agents_service run --package agents_service -m pytest`
  - `uv --directory services/memory_service run --package memory_service -m pytest`
  - `uv --directory packages/bt_common run --package bt_common -m pytest`
- CLI help: `uv run --package bt_cli bibliotalk --help`

### Configuration

- Repo env template: `.env.example`
- Local Matrix stack secrets/config: `deploy/local/matrix/.env` (generated; gitignored)

### Naming

“Spirit” is the user-facing term. Some internal identifiers may still reference the older “Ghost” name while the transition is in progress.
