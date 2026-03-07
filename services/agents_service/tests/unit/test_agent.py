from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from agents_service.models.citation import Evidence


@dataclass
class FakeLlm:
    model_name: str
    calls: int = 0

    async def generate(self, *, persona_prompt: str, query: str, evidence: list[Evidence]) -> str:
        self.calls += 1
        return f"Answer from {self.model_name}: {query} [^1]"


class FakeRegistry:
    def __init__(self) -> None:
        self.models: dict[str, FakeLlm] = {}

    def register(self, model: str, llm: FakeLlm) -> None:
        self.models[model] = llm

    def resolve(self, model: str) -> FakeLlm:
        return self.models[model]


class FakeSupabase:
    def __init__(self) -> None:
        self.agent_id = uuid4()

    async def get_agent(self, agent_id):
        if str(agent_id) != str(self.agent_id):
            return None
        return {
            "id": str(self.agent_id),
            "display_name": "Confucius (Ghost)",
            "persona_prompt": "You are Confucius.",
            "llm_model": "gemini-2.5-flash",
        }

    async def get_agent_emos_config(self, agent_id):
        return {
            "agent_id": str(agent_id),
            "tenant_prefix": str(agent_id),
            "emos_base_url": "https://emos.local",
        }

    async def get_segments_by_ids(self, segment_ids):
        return [
            {
                "id": str(segment_ids[0]),
                "agent_id": str(self.agent_id),
                "text": "Learning without thought is labor lost.",
            }
        ]


@pytest.mark.anyio
async def test_agent_factory_creates_llm_agent_with_correct_persona_prompt() -> None:
    from agents_service.agent.agent_factory import create_ghost_agent

    supabase = FakeSupabase()
    registry = FakeRegistry()
    registry.register("gemini-2.5-flash", FakeLlm("gemini-2.5-flash"))

    agent = await create_ghost_agent(supabase.agent_id, store=supabase, llm_registry=registry)

    assert agent.name == "Confucius (Ghost)"
    assert agent.instruction == "You are Confucius."


@pytest.mark.anyio
async def test_agent_calls_memory_search_tool_when_given_factual_question() -> None:
    from agents_service.agent.agent_factory import create_ghost_agent

    supabase = FakeSupabase()
    registry = FakeRegistry()
    registry.register("gemini-2.5-flash", FakeLlm("gemini-2.5-flash"))
    called = {"value": 0}

    async def fake_memory_search(query: str, agent_id: str):
        called["value"] += 1
        return [
            Evidence(
                segment_id=uuid4(),
                emos_message_id="a:b:c:seg:1",
                source_title="Analects",
                source_url="https://example.com",
                text="Learning without thought is labor lost.",
                platform="gutenberg",
            )
        ]

    agent = await create_ghost_agent(
        supabase.agent_id,
        store=supabase,
        llm_registry=registry,
        memory_search_fn=fake_memory_search,
    )

    await agent.run("What did you say about learning?")

    assert called["value"] == 1


@pytest.mark.anyio
async def test_agent_calls_emit_citations_with_evidence_objects() -> None:
    from agents_service.agent.agent_factory import create_ghost_agent

    supabase = FakeSupabase()
    registry = FakeRegistry()
    registry.register("gemini-2.5-flash", FakeLlm("gemini-2.5-flash"))
    seen = {"count": 0}

    evidence = Evidence(
        segment_id=uuid4(),
        emos_message_id="a:b:c:seg:1",
        source_title="Analects",
        source_url="https://example.com",
        text="Learning without thought is labor lost.",
        platform="gutenberg",
    )

    async def fake_memory_search(query: str, agent_id: str):
        return [evidence]

    async def fake_emit(evidence_items, agent_id):
        seen["count"] = len(evidence_items)
        return []

    agent = await create_ghost_agent(
        supabase.agent_id,
        store=supabase,
        llm_registry=registry,
        memory_search_fn=fake_memory_search,
        emit_citations_fn=fake_emit,
    )

    await agent.run("What did you say about learning?")

    assert seen["count"] == 1


@pytest.mark.anyio
async def test_agent_responds_with_no_evidence_when_memory_search_returns_empty() -> None:
    from agents_service.agent.agent_factory import create_ghost_agent

    supabase = FakeSupabase()
    registry = FakeRegistry()
    registry.register("gemini-2.5-flash", FakeLlm("gemini-2.5-flash"))

    async def empty_memory_search(query: str, agent_id: str):
        return []

    agent = await create_ghost_agent(
        supabase.agent_id,
        store=supabase,
        llm_registry=registry,
        memory_search_fn=empty_memory_search,
    )

    response = await agent.run("What did you say about learning?")

    assert "no evidence" in response["text"].lower()


@pytest.mark.anyio
async def test_agent_uses_correct_llm_model_from_config() -> None:
    from agents_service.agent.agent_factory import create_ghost_agent

    supabase = FakeSupabase()
    registry = FakeRegistry()
    llm = FakeLlm("gemini-2.5-flash")
    registry.register("gemini-2.5-flash", llm)

    evidence = Evidence(
        segment_id=uuid4(),
        emos_message_id="a:b:c:seg:1",
        source_title="Analects",
        source_url="https://example.com",
        text="Learning without thought is labor lost.",
        platform="gutenberg",
    )

    async def fake_memory_search(query: str, agent_id: str):
        return [evidence]

    agent = await create_ghost_agent(
        supabase.agent_id,
        store=supabase,
        llm_registry=registry,
        memory_search_fn=fake_memory_search,
    )

    await agent.run("What did you say about learning?")

    assert llm.calls == 1
    assert agent.model == "gemini-2.5-flash"


@pytest.mark.anyio
async def test_agent_handles_memory_outage_gracefully() -> None:
    from agents_service.agent.agent_factory import create_ghost_agent

    supabase = FakeSupabase()
    registry = FakeRegistry()
    registry.register("gemini-2.5-flash", FakeLlm("gemini-2.5-flash"))

    class _FakeEmosError(Exception):
        pass

    async def failing_memory_search(query: str, agent_id: str):
        _ = query
        _ = agent_id
        raise _FakeEmosError("down")

    agent = await create_ghost_agent(
        supabase.agent_id,
        store=supabase,
        llm_registry=registry,
        memory_search_fn=failing_memory_search,
    )

    response = await agent.run("What did you say about learning?")

    assert "memory" in response["text"].lower()
    assert response["citations"] == []
