# Research: Agent Service

**Feature**: 001-agent-service
**Date**: 2026-02-28

## R1: Testing Strategy — CLI Harness vs Matrix-First

**Decision**: Defer Matrix integration. Build agent core with a CLI test
harness and pytest-driven testing first.

**Rationale**:
- Google ADK provides `InMemoryRunner` for programmatic agent invocation
  without any web server or transport layer. Agents can be instantiated
  and called from pytest or a CLI script.
- The core value (agent + memory search + citations) is independent of
  Matrix. Testing through Matrix requires Synapse deployment, appservice
  registration, and mautrix setup — heavy infrastructure for validating
  agent behavior.
- Constitution Principle VI (Principled Simplicity) favors the simplest
  testable approach first. Constitution Principle IV (Incremental
  Delivery) requires MVP text chat to work end-to-end before adding
  advanced features.
- A `bt_cli` harness (stdin/stdout chat with a Ghost) enables
  rapid iteration on persona tuning, citation quality, and memory
  search without the Synapse round-trip.

**Alternatives Considered**:
1. **Matrix-first** (blueprint order): Build Synapse + appservice first,
   then agent. Rejected because it front-loads infrastructure and
   delays testing of the core agent logic.
2. **HTTP API first**: Expose agents via FastAPI endpoints, test with
   curl/httpie. Viable but unnecessary — ADK's InMemoryRunner is
   lighter. The FastAPI appservice layer comes later with Matrix.

**Implementation Order**:
1. bt_common (EMOS client, citation schemas, segment models) — pytest
2. Ghost agent with ADK — InMemoryRunner + mock EMOS
3. bt_cli test harness — stdin/stdout end-to-end grounding validation
4. Matrix appservice layer (agents_service proper)
5. Multi-agent discussions (streaming floor control)
6. Voice (voice_call_service + voice backends)

## R2: Google ADK Agent Testing

**Decision**: Use ADK's `InMemoryRunner` for programmatic testing,
`BaseLlm` subclass for mock LLM responses in deterministic tests.

**Rationale**:
- ADK agents are plain Python objects (`LlmAgent`) that can be
  instantiated directly. No web server required.
- `InMemoryRunner` provides a `run()` method that accepts a user
  message and returns the agent's response, including tool calls.
- For deterministic unit tests, implement a `MockLlm(BaseLlm)` that
  returns canned responses. Register via `LLMRegistry.register()`.
- For integration tests with real LLMs, use `InMemoryRunner` with
  the actual Gemini or Nova backend.

**Key Code Pattern**:
```python
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner

agent = LlmAgent(name="test_ghost", model="gemini-2.5-flash",
                  instruction="You are Confucius.", tools=[memory_search])
runner = InMemoryRunner(agent=agent)
response = await runner.run("What is the meaning of virtue?")
```

## R3: EverMemOS Client Design

**Decision**: Build an async Python client using `httpx.AsyncClient`
with Pydantic request/response models.

**Rationale**:
- EMOS API surface: POST /memories (memorize), GET /memories/search
  (retrieve), GET/POST/PATCH /memories/conversation-meta (metadata).
- No API-level authentication — designed for private network. Bibliotalk
  adds auth at the infrastructure layer.
- Search uses JSON body on GET request — `httpx.request("GET", ...,
  json=body)` handles this.
- Five retrieval methods: keyword, vector, hybrid, rrf, agentic.
  Bibliotalk uses rrf (fast) with agentic fallback.

**Testing Tiers**:
| Tier        | Tool                     | What It Tests                       |
| ----------- | ------------------------ | ----------------------------------- |
| Unit        | `respx` / `pytest-httpx` | Client serialization, error paths   |
| Contract    | Fixture JSON files       | Response parsing, schema compliance |
| Integration | Docker Compose + EMOS    | Full round-trip memorize → search   |

**Key Design Decisions**:
- Memorize returns `status_info: "extracted" | "accumulated"` — the
  client must handle both (accumulated means queued, not yet processed).
- Search response groups memories by type in a nested structure —
  client must flatten and extract `group_id` values.
- EMOS requires valid LLM/embedding API keys even for local testing
  (the extraction pipeline calls LLMs internally).

## R4: Nova Sonic Voice Backend

**Decision**: Implement `NovaSonicBackend(VoiceBackend)` using
Bedrock's `InvokeModelWithBidirectionalStreamCommand`.

**Rationale**:
- Nova Sonic uses bidirectional HTTP/2 streaming via an async iterator
  pattern. Events are sent/received as structured JSON envelopes.
- Tool-use IS supported mid-conversation. The model can pause audio
  output, emit a `toolUse` event (with tool name and parameters),
  wait for the tool result, then resume generating audio.
- Audio format: PCM 16-bit, 16kHz mono input; PCM 16-bit, 24kHz
  mono output (configurable).

**Session Lifecycle**:
1. Send `sessionStart` event (system prompt, tools, audio config)
2. Send `promptStart` → audio content start → audio chunks (PCM)
3. Receive: audio chunks, transcript events, tool-use events
4. On tool-use: send tool result, model resumes
5. Send `sessionEnd` to close

**Testing**:
- Can test with pre-recorded PCM audio files — no live mic required.
- Unit tests: mock the Bedrock client, verify event serialization.
- Integration: requires AWS credentials and us-east-1 region access.
- Test tool-use flow: send audio → model requests memory_search →
  return mock evidence → model generates grounded voice response.

## R5: Floor-Control Protocol for Multi-Agent Discussions

**Decision**: Use a per-room in-process Discussion Controller in
`agents_service` as the single authority for turn-taking, interruption,
and streaming. Ghost runners never post directly; they submit
`REQUEST_FLOOR` intents. The controller grants one speaker at a time and
can cancel in-flight output immediately.

**Rationale**:
- Matrix is the shared transcript, but room observation alone is
  insufficient for live streaming discussions with interruption.
- A single authority is required to prevent reply storms, enforce
  deterministic ordering, and support hard preemption (especially user
  barge-in for voice).
- `REQUEST_FLOOR(force: bool)` is simpler than separate interrupt APIs:
  - `force=true` can preempt only an active **agent** speaker.
  - Agents may request while a user speaks, but must use `force=false`.
- Scheduler quality improves when scoring includes mention priority and
  evidence readiness, not only static turn order.

**Protocol Shape**:
- Inputs normalized to `UtteranceEvent` from Matrix + VAD/ASR.
- Floor state machine: `IDLE`, `USER_SPEAKING`, `AGENT_SPEAKING`.
- User speech has absolute priority; on user start, controller cancels
  active agent generation/TTS immediately.
- Scheduler selects next speaker using weighted score:
  mention boost + relevance + urgency + fairness + evidence.
  Topic coherence is part of relevance.

**Testing**:
- Unit tests for state transitions, force rules, and cancellation.
- Contract tests for `REQUEST_FLOOR` and controller decisions.
- Integration tests for text and voice barge-in behavior:
  user interruption stops agent output with bounded latency.

## R6: LLM Backend Swapping

**Decision**: Use ADK's `LLMRegistry` to register Nova Lite v2 as a
custom backend alongside built-in Gemini. Per-agent model selection
via `agents.llm_model` column.

**Rationale**:
- ADK resolves models via `LLMRegistry`. Gemini models are built-in.
  Custom models (Nova Lite v2 via Bedrock Converse API) require a
  `BaseLlm` subclass registered at startup.
- Switching models is a config change: update `agents.llm_model`
  in Supabase, agent recreated on next invocation.
- Both backends support tool-use (function calling), which is required
  for `memory_search` and `emit_citations`.
