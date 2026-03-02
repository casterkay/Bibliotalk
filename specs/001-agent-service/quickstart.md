# Quickstart: Agent Service

**Feature**: 001-agent-service
**Prerequisites**: Python 3.11+, Node.js 20+ (for voice sidecar)

## 1. Setup

```bash
# Clone and enter the project
cd Bibliotalk

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"  # or: uv sync

# Copy environment template
cp .env.example .env
# Edit .env with your API keys:
#   GOOGLE_API_KEY=...          (Gemini API)
#   SUPABASE_URL=...
#   SUPABASE_SERVICE_ROLE_KEY=...
#   EMOS_BASE_URL=...
```

## 2. Quick Test (CLI Harness)

The fastest way to test a Ghost agent — no Matrix/Synapse required:

```bash
# Start a CLI chat with a Ghost (uses mock EMOS data)
python -m bt_cli --agent confucius --mock-emos

# Start with real EMOS instance
python -m bt_cli --agent confucius
```

Example session:
```
> What did you say about learning?
Confucius (Ghost): The pursuit of learning is endless.
As I once reflected, "Learning without thought is labor
lost; thought without learning is perilous."¹

──────────
Sources:
[1] The Analects, Book II — gutenberg:3330
```

## 3. Run Tests

```bash
# Unit tests (no external services needed)
pytest tests/unit/ -v

# Contract tests (EMOS client mock validation)
pytest tests/contract/ -v

# Integration tests (requires Docker Compose for EMOS)
docker compose -f docker-compose.test.yml up -d
pytest tests/integration/ -v -m integration
docker compose -f docker-compose.test.yml down
```

## 4. Start the Full Service (with Matrix)

```bash
# Ensure Synapse is running and appservice is registered
# Start agents_service
uvicorn agents_service.main:app --host 0.0.0.0 --port 8009

# Start voice_call_service (for voice calls)
cd services/voice_call_service && npm start
```

## 5. Verify

1. Open Element, log into `bibliotalk.space`
2. Start a DM with `@btghost_confucius:bibliotalk.space`
3. Send: "What is the meaning of virtue?"
4. Ghost should respond with grounded citations

## Project Structure

```
bt_common/                  # Shared Python library
├── evermemos_client.py          # Async EMOS HTTP client
├── citation.py             # Citation models + validation
├── segment.py              # Segment models + BM25 re-ranking
└── matrix_helpers.py       # Message formatting

services/agents_service/src/                   # Core agent service
├── main.py                 # FastAPI appservice entry point
├── appservice.py           # Matrix event handler (mautrix)
├── agent_factory.py        # ADK agent creation
├── tools/
│   ├── memory_search.py    # EMOS retrieve + re-rank
│   └── emit_citations.py   # Citation attachment
├── voice/
│   ├── session_manager.py  # Voice session lifecycle
│   └── backends/
│       ├── base.py         # VoiceBackend ABC
│       ├── nova_sonic.py   # Nova Sonic backend
│       └── gemini_live.py  # Gemini Live backend
└── discussion/
    ├── orchestrator.py     # Multi-agent discussion flow
    └── floor_controller.py # Floor manager + scheduler

services/voice_call_service/src/           # Node.js voice bridge
├── index.js                # Entry point
├── matrixrtc.js            # MatrixRTC client
└── audio_bridge.js         # WebSocket bridge to agents_service

bt_cli/                     # CLI test harness
└── __main__.py             # stdin/stdout Ghost chat

tests/
├── unit/                   # No external deps
├── contract/               # Mock HTTP responses
└── integration/            # Docker Compose + real services
```
