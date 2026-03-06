"""Database access abstraction for agents_service.

The logical schema is defined in BLUEPRINT.md (relational/Postgres dialect).
For local E2E development we use SQLite via SQLAlchemy, so this interface is
intentionally small and focused on the queries required by the runtime and
bootstrap tooling.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class Store(Protocol):
    async def aclose(self) -> None: ...

    # Agents / config
    async def get_agent(self, agent_id: UUID) -> dict[str, Any] | None: ...
    async def get_agent_by_matrix_id(
        self, matrix_user_id: str
    ) -> dict[str, Any] | None: ...
    async def get_agent_emos_config(self, agent_id: UUID) -> dict[str, Any] | None: ...

    # Rooms
    async def is_profile_room(self, matrix_room_id: str) -> bool: ...

    # Retrieval/citations
    async def get_sources_by_emos_group_ids(
        self, emos_group_ids: list[str]
    ) -> list[dict[str, Any]]: ...
    async def get_segments_by_source_ids(
        self, source_ids: list[str]
    ) -> list[dict[str, Any]]: ...
    async def get_segments_by_ids(
        self, segment_ids: list[UUID]
    ) -> list[dict[str, Any]]: ...
    async def get_segments_for_agent(self, agent_id: UUID) -> list[dict[str, Any]]: ...

    # Audit
    async def save_chat_history(self, record: dict[str, Any]) -> dict[str, Any]: ...
