from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from bt_store.models_core import Agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("discord_service")


@dataclass(frozen=True, slots=True)
class AgentInfo:
    agent_id: uuid.UUID
    agent_slug: str
    display_name: str
    persona_summary: str | None


class AgentDirectory:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        logger_: logging.Logger | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._logger = logger_ or logger
        self._by_id: dict[uuid.UUID, AgentInfo] = {}
        self._by_slug_lower: dict[str, AgentInfo] = {}
        self._by_display_lower: dict[str, list[AgentInfo]] = {}

    async def refresh(self) -> None:
        async with self._session_factory() as session:
            agents = (
                (
                    await session.execute(
                        select(Agent)
                        .where(Agent.is_active.is_(True))
                        .order_by(Agent.slug)
                    )
                )
                .scalars()
                .all()
            )

        by_id: dict[uuid.UUID, AgentInfo] = {}
        by_slug_lower: dict[str, AgentInfo] = {}
        by_display_lower: dict[str, list[AgentInfo]] = {}
        for agent in agents:
            info = AgentInfo(
                agent_id=agent.agent_id,
                agent_slug=agent.slug,
                display_name=agent.display_name,
                persona_summary=agent.persona_summary,
            )
            by_id[info.agent_id] = info
            by_slug_lower[info.agent_slug.lower()] = info
            by_display_lower.setdefault(info.display_name.lower(), []).append(info)

        self._by_id = by_id
        self._by_slug_lower = by_slug_lower
        self._by_display_lower = by_display_lower
        self._logger.info("agent directory refreshed count=%s", len(self._by_id))

    def list_agents(self) -> list[AgentInfo]:
        return list(self._by_id.values())

    def get_by_id(self, agent_id: uuid.UUID) -> AgentInfo | None:
        return self._by_id.get(agent_id)

    def resolve_token(self, token: str) -> AgentInfo | None:
        key = (token or "").strip()
        if not key:
            return None
        slug_match = self._by_slug_lower.get(key.lower())
        if slug_match:
            return slug_match

        display_matches = self._by_display_lower.get(key.lower())
        if display_matches:
            return display_matches[0]

        # Soft match: substring against slug and display name.
        lowered = key.lower()
        for info in self._by_id.values():
            if (
                lowered in info.agent_slug.lower()
                or lowered in info.display_name.lower()
            ):
                return info
        return None

    def resolve_override_prefix(self, content: str) -> str | None:
        stripped = (content or "").lstrip()
        if not stripped.startswith("@"):
            return None
        token = stripped[1:].split(maxsplit=1)[0]
        token = token.rstrip(":,;.!?").strip()
        return token or None
