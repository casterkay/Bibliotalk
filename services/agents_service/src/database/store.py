"""Database access abstraction for agents_service.

This protocol captures only the retrieval operations still needed by the
trimmed agent library after the Matrix-era runtime and ORM implementation were
removed from the repository.
"""

from __future__ import annotations

from typing import Protocol, TypedDict
from uuid import UUID


class AgentRow(TypedDict, total=False):
    id: str
    kind: str
    display_name: str
    persona_prompt: str
    llm_model: str
    is_active: bool
    created_at: str | None


class AgentEmosConfigRow(TypedDict, total=False):
    agent_id: str
    emos_base_url: str
    emos_api_key_encrypted: str | None
    emos_api_key: str | None
    tenant_prefix: str


class SourceRow(TypedDict, total=False):
    id: str
    agent_id: str
    platform: str
    external_id: str
    external_url: str | None
    title: str
    author: str | None
    published_at: str | None
    emos_group_id: str


class SegmentRow(TypedDict, total=False):
    id: str
    agent_id: str
    source_id: str
    platform: str
    seq: int
    text: str
    sha256: str
    emos_message_id: str
    source_title: str | None
    source_url: str | None
    speaker: str | None
    start_ms: int | None
    end_ms: int | None


class Store(Protocol):
    async def aclose(self) -> None: ...

    async def get_agent(self, agent_id: UUID) -> AgentRow | None: ...
    async def get_agent_emos_config(self, agent_id: UUID) -> AgentEmosConfigRow | None: ...

    async def get_sources_by_emos_group_ids(self, emos_group_ids: list[str]) -> list[SourceRow]: ...
    async def get_segments_by_source_ids(self, source_ids: list[str]) -> list[SegmentRow]: ...
    async def get_segments_by_ids(self, segment_ids: list[UUID]) -> list[SegmentRow]: ...
    async def get_segments_for_agent(self, agent_id: UUID) -> list[SegmentRow]: ...
