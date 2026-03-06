# Research: Agent Service

**Feature**: `001-agent-service`  
**Created**: 2026-02-28  
**Last Updated**: 2026-03-03

## R0: Agent Runtime — Google ADK vs Minimal Local Runtime

**Decision**: Treat Google ADK as the *target* runtime (per `BLUEPRINT.md`), but keep a minimal local `GhostAgent` runtime in-repo until retrieval + citation correctness is solid.

**Rationale**:
- The riskiest/most user-visible behavior is grounding + citation validation. A minimal runtime keeps iteration tight while contracts harden.
- ADK integration must preserve the same tool contracts (`memory_search`, `emit_citations`) and the same validation rules (quotes must be verifiable substrings of canonical segments).

**Implication**:
- Specs/contracts assume ADK-style tool usage; current code may implement the same behaviors without ADK while the contracts stabilize.

## R1: Testing Strategy — CLI Harness vs Matrix-First

**Decision**: CLI-first testing. Defer full Synapse/appservice deployment until P1 grounding + citations are reliable.

**Rationale**:
- The core value (agent + memory search + citations) is independent of Matrix transport.
- A CLI harness reduces infrastructure friction and supports rapid persona/citation tuning.
- Matrix integration adds additional failure modes (auth, appservice registration, event schemas, rate limits).

**Implementation note**:
- The CLI harness lives at `services/agents_service/src/__main__.py` and is invoked via `python -m agents_service ...`.
- `format_ghost_response` is owned by `services/agents_service/src/matrix/appservice.py` and reused by the CLI and voice transcript paths (per `BLUEPRINT.md`).

## R2: Contract & Unit Test Placement (Monorepo)

**Decision**:
- Infra/SDK wrapper tests live with infra (`packages/bt_common/tests/`).
- Agent-domain tests live with the agent service (`services/agents_service/tests/`).

**Rationale**:
- `bt_common` is infra-only (config/logging/exceptions + EverMemOS wrapper).
- Citation/segment models are agent-domain and belong to `services/agents_service/src/models/` (per `BLUEPRINT.md`).

## R3: EverMemOS Client Design

**Decision**: Use the `evermemos` SDK with a thin wrapper for retries and domain-specific error mapping.

**Rationale**:
- The SDK already tracks payload conventions and endpoint quirks; the wrapper standardizes retries + error classes.
- EverMemOS deployments may vary across versions (e.g., API path/version in error envelopes). Contracts should focus on **shapes** and **id conventions**, not fragile URL strings.

**Testing tiers**:
| Tier        | Location                         | What it tests                                  |
| ----------- | -------------------------------- | ---------------------------------------------- |
| Unit        | `packages/bt_common/tests/unit/` | retry behavior, error mapping, config loading  |
| Contract    | `packages/bt_common/tests/contract/` | captured response shape expectations        |

## R4: Voice Backends (Nova Sonic / Gemini Live)

**Decision**: Define a `VoiceBackend` ABC and implement backends behind it.

**Rationale**:
- Both engines should support: audio in/out + transcripts + mid-session tool calls.
- A stable ABC keeps voice orchestration independent of vendor differences.

**Audio format** (per `BLUEPRINT.md`):
- Input: PCM 16-bit mono @ 16kHz
- Output: PCM 16-bit mono @ 24kHz

## R5: Floor-Control Protocol (Multi-Agent Discussions)

**Decision**: Single room-level authority inside `agents_service` enforces turn-taking and cancellation.

**Rationale**:
- Prevents reply storms and non-determinism in multi-Ghost rooms.
- Required for voice barge-in: user interruption must cancel in-flight agent output immediately.

**Key rule**:
- Agent identifiers in floor-control should use the **agent UUID** (`agents.id`). Matrix user IDs are a separate field (`agents.matrix_user_id`).

## R6: LLM Backend Swapping

**Decision**: Model selection is per-agent config (e.g., `agents.llm_model`), resolved at agent creation time.

**Rationale**:
- Allows switching Gemini ↔ Nova Lite v2 by configuration.
- Keeps higher-level orchestration stable while swapping generation engines.

## R7: Local E2E Storage Backend (SQLite + SQLAlchemy)

**Decision**: For local end-to-end development (“let me chat with ghosts”), use SQLite behind a SQLAlchemy ORM store that holds the same logical entities as the blueprint’s relational schema.

**Rationale**:
- Local E2E chat requires a canonical store of verbatim `segments` to validate citations and to post profile-room timelines.
- EverMemOS retrieval returns `group_id` but is not treated as a canonical segment store for verifiable quotes.
- SQLite provides a lightweight local backend suitable for a scripted bootstrap flow (seed Ghosts, import segment cache, provision Matrix rooms).
