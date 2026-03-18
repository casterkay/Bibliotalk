"""Discord DM orchestration and legacy discussion helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

A2AClient = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
PostMessage = Callable[[str, dict[str, Any]], Awaitable[None]]
AgentFactory = Callable[[UUID], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class DMContext:
    agent_id: UUID
    agent_slug: str
    discord_user_id: str
    discord_channel_id: str
    content: str


@dataclass(frozen=True, slots=True)
class DMResponse:
    response_text: str
    citations: list[str]
    evidence: list[Any]


class DMOrchestrator:
    def __init__(self, *, agent_factory: AgentFactory):
        self.agent_factory = agent_factory

    async def run(self, context: DMContext) -> DMResponse:
        agent = await self.agent_factory(context.agent_id)
        result = await agent.run(context.content)
        return DMResponse(
            response_text=result.get("text", ""),
            citations=list(result.get("citations", [])),
            evidence=list(result.get("evidence", [])),
        )


@dataclass
class DiscussionConfig:
    topic: str
    spirit_agent_ids: list[str]
    max_turns: int = 4
    turn_order: str = "round-robin"


class DiscussionOrchestrator:
    def __init__(
        self,
        *,
        a2a_client: A2AClient,
        post_message: PostMessage,
    ):
        self.a2a_client = a2a_client
        self.post_message = post_message

    async def run(self, room_id: str, config: DiscussionConfig) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        if not config.spirit_agent_ids:
            return history

        for turn in range(config.max_turns):
            spirit_id = config.spirit_agent_ids[turn % len(config.spirit_agent_ids)]
            context_lines = [config.topic] + [item["text"] for item in history]
            prompt = "\n".join(context_lines)

            request = {
                "jsonrpc": "2.0",
                "id": str(uuid4()),
                "method": "tasks/send",
                "params": {
                    "id": str(uuid4()),
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": prompt}],
                    },
                },
            }
            response = await self.a2a_client(spirit_id, request)
            artifacts = response["result"]["artifacts"][0]["parts"]
            text = artifacts[0]["text"]
            citations = artifacts[1]["data"].get("citations", [])

            turn_payload = {"spirit_id": spirit_id, "text": text, "citations": citations}
            history.append(turn_payload)
            await self.post_message(room_id, turn_payload)

        return history
