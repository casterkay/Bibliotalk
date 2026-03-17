# Implementation Plan: Matrix MVP (Archive + Dialogue + Voice)

**Branch**: `001-matrix-mvp` | **Date**: 2026-03-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification at `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/spec.md`

## Summary

Deliver a Matrix-first Bibliotalk MVP with two room types:

- **Archive Rooms**: public, read-only rooms posted idempotently as per-source threads (root = deterministic source summary from ingestion / EverMemOS metadata; replies = verbatim transcript excerpts).
- **Dialogue Rooms**: private rooms where users can interact with Spirits via grounded text chat and 1:1 voice calls, with streaming-first interactions (users can send messages while Spirit output streams).

Rearchitect the backend so Spirit reasoning, grounding, and citation validation are platform-agnostic, with Matrix implemented as the first production adapter and Discord treated as a later adapter.

## Technical Context

**Language/Version**: Python 3.11+ (core services), Node.js 20+ (Matrix adapter + MatrixRTC voice sidecar)
**Primary Dependencies**: Python: `fastapi`, `uvicorn`, `httpx`, `pydantic>=2`, `SQLAlchemy>=2`, `aiosqlite`, `alembic`, `tenacity`, EverMemOS SDK (`bt_common.evermemos_client`), Gemini via ADK (text) and Gemini Live (voice). Node: `matrix-js-sdk`, `ws` *(and a minimal HTTP server framework such as `fastify` for the appservice endpoint).*
**Storage**: SQLite for local development; Postgres for production; one logical relational schema shared by ingestion + agent + Matrix adapter
**Testing**: `pytest` + `pytest-asyncio` (Python); Node built-in `node:test` for Matrix adapter + sidecar unit tests; integration tests for Matrix text chat, Archive publication, and voice transcript+citations flow
**Target Platform**: local dev via Docker Compose; production on Linux (containerized)
**Project Type**: multi-service backend (ingestion + agent core + Matrix adapter + voice sidecar)
**Performance Goals**: median text-turn latency < 5s for evidence-backed questions; median voice-turn latency < 3s from end-of-user-utterance to start-of-Spirit-speech in controlled tests
**Constraints**: no AI responses in Archive Rooms; strict cross-Spirit evidence isolation; idempotent Archive publication; secrets never logged; voice MVP is unencrypted; Discord may temporarily break during rearchitecture
**Scale/Scope**: MVP target of 50 concurrent Dialogue Rooms (text and/or voice) and 10–50 Spirits

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                        | Gate                                                                                                                               | Status |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------ |
| I. Design-First Architecture     | `spec.md` exists; Phase 0/1 produce research, data model, and contracts before implementation begins                               | PASS   |
| II. Test-Driven Quality          | Add unit/contract/integration tests for routing, citation validation, Archive enforcement, and voice transcript flow               | PASS   |
| III. Contract-Driven Integration | Define typed contracts for Matrix inbound/outbound events, citations, agent turn API, and voice bridge protocol before integration | PASS   |
| IV. Incremental Delivery         | Ship in P1→P2→P3 order (Dialogue text → Archive publication → 1:1 voice); each increment demoable end-to-end                       | PASS   |
| V. Observable Systems            | Structured logs and correlation IDs for Matrix transactions, agent turns, ingestion publishes, and voice sessions                  | PASS   |
| VI. Principled Simplicity        | Only introduce abstractions used by Matrix now and Discord later; all complexity deviations are explicitly justified               | PASS   |

**Re-check (post Phase 1 artifacts)**: PASS — contracts and data model are explicitly defined; phased delivery remains incremental.

## Project Structure

### Documentation (this feature)

```text
specs/001-matrix-mvp/
├── spec.md              # Feature specification (already written)
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command; not created here)
```

### Source Code (repository root)

```text
packages/
├── bt_common/                      # infra-only (config/logging/exceptions/EMOS client)
└── bt_store/                       # shared relational schema + migrations (service-agnostic)

services/
├── memory_service/              # writes sources/segments; triggers Archive publication intents
├── agents_service/                 # platform-agnostic Spirit core (turn handling, grounding, citations, voice orchestration)
├── matrix_service/                 # Node/TS Matrix appservice adapter (Archive/Dialogue semantics, event routing, posting)
├── voip_service/             # Node MatrixRTC/WebRTC sidecar; audio bridge to agents_service
└── memory_page_service/            # public memory pages (optional but strongly recommended)

packages/bt_cli/                    # operator CLI entrypoints to run services and bootstrap env
```

**Structure Decision**: Keep the platform-agnostic Spirit logic in `services/agents_service/`. Keep the relational schema in `packages/bt_store/` so all services share the same data model without importing each other. Implement Matrix transport as a thin adapter in `services/matrix_service/` (Node/TS) using `matrix-js-sdk` for client-server interactions and a minimal HTTP framework for appservice endpoints. Keep WebRTC/media handling in `services/voip_service/` as a separate sidecar process that only bridges audio to `agents_service`.

**Streaming Decision (MVP)**:
- Prefer Live Sessions (`specs/001-matrix-mvp/contracts/agent-turn-api.md`) for full-duplex streaming (text and voice). Keep a non-streaming turn endpoint only as a compatibility fallback.
- Voice transcripts are sourced from Gemini Live’s built-in input/output transcription streams (no separate ASR transcript contract required).
- Citation marker style is adapter-owned and implementation-defined per platform; the agent core returns plain text + structured citations and the adapter formats for Matrix/Discord.

## Phased Delivery

| Phase | Deliverable                                                                                  | Feature Scope Slice |
| ----- | -------------------------------------------------------------------------------------------- | ------------------- |
| P1    | Matrix adapter + grounded text turns in Dialogue Rooms with verifiable citations             | User Story 1        |
| P2    | Archive Rooms: room provisioning + idempotent per-source thread publication of ingested text | User Story 2        |
| P3    | 1:1 voice calls in Dialogue Rooms: audio bridge + transcript + citations posted in-room      | User Story 3        |

## Complexity Tracking

| Violation / Deviation                        | Why Needed                                                                 | Simpler Alternative Rejected Because                                       |
| -------------------------------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Additional runtime: Node voice sidecar       | MatrixRTC/WebRTC media handling is isolated and uses mature JS ecosystem   | Implementing WebRTC + Opus + MatrixRTC reliably in Python is high risk     |
| Platform abstraction contracts (turn + cite) | Enables Matrix-first delivery without duplicating Spirit core and citations | Per-platform custom logic would diverge quickly and break trust invariants |
| Separate `matrix_service` adapter runtime    | Keeps Matrix concerns out of agent core and preserves portability          | Embedding Matrix transport into agent core couples deployment and testing  |
