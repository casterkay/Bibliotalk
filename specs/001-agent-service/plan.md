# Implementation Plan: Agent Service

**Feature**: `001-agent-service` | **Date**: 2026-03-02 | **Spec**: [spec.md](./spec.md)  
**Input**: `BLUEPRINT.md` + the design docs in `specs/001-agent-service/`

## Summary

Implement `agents_service`, the Matrix appservice + runtime that powers Ghosts (AI digital twins) with EverMemOS-grounded responses and verifiable citations (**言必有據**). The service also owns multi-agent discussion orchestration (floor control) and coordinates with `voice_call_service` for MatrixRTC voice sessions.

This repository contains an end-to-end text chat loop (Matrix appservice → retrieval → LLM composition → citations → Matrix response). The agent runtime is now wired to **Google ADK** for Gemini-backed text generation (see `services/agents_service/src/agent/providers/gemini.py`). Future work should extend ADK usage to richer tool-calling orchestration, additional providers (Bedrock Nova), and the planned multi-agent floor-control flows, while preserving the tool contracts (`memory_search`, `emit_citations`) and citation validation rules.

## Technical Context

**Languages**: Python 3.11+ (`services/agents_service`, `packages/bt_common`); Node.js 20+ (`services/voice_call_service`)  
**Key deps (current)**:
- Python: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `httpx`, `evermemos`, `supabase`
- Node: `matrix-js-sdk`, `ws`
**Key deps (target, per blueprint)**: Google ADK, Gemini APIs, AWS Bedrock (Nova Lite v2 / Nova Sonic)

**Storage**: Supabase Postgres (agents, segments, chat_history, …), EverMemOS (memory)  
**Performance goals**: <5s text response latency; <3s voice response latency  
**Constraints**: unencrypted voice for MVP; single homeserver; appservice reserves `@bt_*` namespace; Ghosts never respond in profile rooms

## Constitution Check

*GATE: Must pass before major implementation changes. Re-check after each milestone.*

| Principle                        | Gate                                                                | Status |
| -------------------------------- | ------------------------------------------------------------------- | ------ |
| I. Design-First Architecture     | `spec.md` + `plan.md` exist before deeper build-out                 | PASS   |
| II. Test-Driven Quality          | Unit tests cover core business logic; contract tests cover EMOS edge | PASS   |
| III. Contract-Driven Integration | Explicit contracts for EMOS, citations, floor control, voice backend | PASS   |
| IV. Incremental Delivery         | US1 before US2 before US3 before US4                                | PASS   |
| V. Observable Systems            | Structured logs + correlation IDs at service entry points           | PASS   |
| VI. Principled Simplicity        | CLI-first harness for rapid iteration                               | PASS   |

## Repository Ownership (authoritative)

From `BLUEPRINT.md` and the current tree:
- `format_ghost_response` owner: `services/agents_service/src/matrix/appservice.py`
- Citation + segment domain models: `services/agents_service/src/models/`
- Agent runtime + tools: `services/agents_service/src/agent/`
- Infra-only shared lib (EMOS client, config, logging, exceptions): `packages/bt_common/src/`

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-service/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── emos-client.md
│   ├── citation-schema.md
│   ├── voice-backend.md
│   └── discussion-floor-control.md
└── tasks.md
```

### Source Code (repository root)

```text
packages/bt_common/src/
└── bt_common/
    ├── config.py                 # pydantic-settings + .env loading
    ├── logging.py                # JSON logging + correlation IDs
    ├── exceptions.py             # shared exception types
    └── evermemos_client.py       # EverMemOS SDK wrapper + retry/error mapping

services/agents_service/src/
└── agents_service/
    ├── __main__.py               # CLI harness (`python -m agents_service ...`)
    ├── server.py                 # FastAPI appservice transaction endpoint
    ├── agent/
    │   ├── agent_factory.py      # Ghost agent creation + caching
    │   ├── orchestrator.py       # (current) simple multi-ghost orchestration
    │   ├── providers/            # (target) LLM backends (Gemini/Nova)
    │   └── tools/
    │       ├── memory_search.py  # EMOS search + local rerank → Evidence
    │       └── emit_citations.py # Evidence → validated citations
    ├── database/
    │   └── supabase_helpers.py
    ├── matrix/
    │   ├── appservice.py         # event handling + `format_ghost_response`
    │   └── guards.py             # per-room rate limiter
    ├── models/
    │   ├── citation.py
    │   └── segment.py
    └── voice/
        ├── session_manager.py
        ├── transcript.py
        └── backends/
            ├── base.py
            ├── nova_sonic.py
            └── gemini_live.py

services/voice_call_service/src/
├── index.js
├── matrixrtc.js
├── audio_bridge.js
└── mixer.js
```

### Tests

```text
packages/bt_common/tests/
services/agents_service/tests/
```

## Phased Delivery (maps to spec priorities)

- **P1 (US1)**: Private text chat with a Ghost, grounded in EverMemOS with verifiable citations.
- **P2 (US2)**: Multi-agent text discussion with floor control (one speaker at a time; user preemption).
- **P3 (US3)**: Voice calls (MatrixRTC sidecar + voice backend tool-use + transcript + citations).
- **P4 (US4)**: Multi-agent voice discussions (floor-gated audio, barge-in, transcript + citations).

## Complexity Tracking

| Decision | Why it exists | Alternative rejected |
| --- | --- | --- |
| Node.js voice sidecar | MatrixRTC/WebRTC media handling is a separate runtime concern | A pure-Python stack still needs WebRTC media plumbing |
| VoiceBackend abstraction | Swap Nova Sonic ↔ Gemini Live without changing orchestration | Backend-specific logic would sprawl across the session manager |
| Domain models in `agents_service` | Keeps agent-domain ownership out of infra package (`bt_common`) | Putting agent models in `bt_common` breaks repository boundaries |

## Proposed Improvements (Non-Blocking)

- Wire `services/voice_call_service/package.json` to run `src/index.js` via `npm start`.
- Make `.env` discovery robust (support repo-root `.env` even when running from service directories).
- Add a dedicated Matrix event contract doc (appservice transactions + message send payloads).
- Implement the `BLUEPRINT.md` retrieval narrowing: EverMemOS `group_id` → `sources/segments` before reranking.
