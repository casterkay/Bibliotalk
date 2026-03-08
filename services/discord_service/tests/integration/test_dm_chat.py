from __future__ import annotations

import uuid
from datetime import UTC, datetime
from importlib import import_module

import pytest


class FakeAgent:
    def __init__(self, response_text: str, evidence: list[object]) -> None:
        self.response_text = response_text
        self.evidence = evidence

    async def run(self, query: str) -> dict:
        _ = query
        return {
            "text": self.response_text,
            "citations": [],
            "evidence": self.evidence,
        }


@pytest.mark.anyio
async def test_dm_handler_returns_valid_inline_memory_link_response() -> None:
    DMOrchestrator = import_module("agents_service.agent.orchestrator").DMOrchestrator
    Evidence = import_module("agents_service.models.citation").Evidence
    DMHandler = import_module("discord_service.bot.dm_handler").DMHandler
    InboundDM = import_module("discord_service.bot.message_models").InboundDM

    figure_id = uuid.uuid4()
    evidence = Evidence(
        segment_id=uuid.uuid4(),
        figure_id=figure_id,
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        text="Learning without thought is labor lost.",
        platform="youtube",
    )

    async def create_agent(_: uuid.UUID) -> FakeAgent:
        return FakeAgent(
            f"He said [Learning without thought is labor lost.]({evidence.memory_url})",
            [evidence],
        )

    async def resolve_slug(_: str) -> str:
        return "alan-watts"

    orchestrator = DMOrchestrator(agent_factory=create_agent)
    handler = DMHandler(orchestrator=orchestrator, figure_slug_resolver=resolve_slug)

    responses = await handler.handle(
        InboundDM(
            discord_message_id="1",
            discord_user_id="2",
            discord_channel_id="3",
            figure_id=figure_id,
            content="What did he say about learning?",
            received_at=datetime.now(tz=UTC),
        )
    )

    assert len(responses) == 1
    assert responses[0].no_evidence is False
    assert responses[0].evidence_used == [evidence.memory_url]


@pytest.mark.anyio
async def test_dm_handler_uses_no_evidence_fallback_when_links_do_not_validate() -> (
    None
):
    DMOrchestrator = import_module("agents_service.agent.orchestrator").DMOrchestrator
    citation_module = import_module("agents_service.models.citation")
    Evidence = citation_module.Evidence
    NO_EVIDENCE_RESPONSE = citation_module.NO_EVIDENCE_RESPONSE
    DMHandler = import_module("discord_service.bot.dm_handler").DMHandler
    InboundDM = import_module("discord_service.bot.message_models").InboundDM

    figure_id = uuid.uuid4()
    evidence = Evidence(
        segment_id=uuid.uuid4(),
        figure_id=figure_id,
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        text="Learning without thought is labor lost.",
        platform="youtube",
    )

    async def create_agent(_: uuid.UUID) -> FakeAgent:
        return FakeAgent(
            f"He said [Fabricated quote]({evidence.memory_url})",
            [evidence],
        )

    async def resolve_slug(_: str) -> str:
        return "alan-watts"

    orchestrator = DMOrchestrator(agent_factory=create_agent)
    handler = DMHandler(orchestrator=orchestrator, figure_slug_resolver=resolve_slug)

    responses = await handler.handle(
        InboundDM(
            discord_message_id="1",
            discord_user_id="2",
            discord_channel_id="3",
            figure_id=figure_id,
            content="What did he say about learning?",
            received_at=datetime.now(tz=UTC),
        )
    )

    assert len(responses) == 1
    assert responses[0].no_evidence is True
    assert responses[0].response_text == NO_EVIDENCE_RESPONSE
