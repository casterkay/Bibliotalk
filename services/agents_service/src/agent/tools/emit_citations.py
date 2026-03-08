"""Emit and validate citations from evidence objects."""

from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from ...models.citation import Evidence, build_inline_link

SegmentsByIdsProvider = Callable[[list[UUID]], Awaitable[list[dict[str, Any]]]]

_last_citations: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "last_citations", default=None
)


class EmitCitationsTool:
    def __init__(self, *, segments_by_ids_provider: SegmentsByIdsProvider):
        self.segments_by_ids_provider = segments_by_ids_provider

    async def __call__(self, evidence_items: list[Evidence], agent_id: str) -> list[str]:
        _ = self.segments_by_ids_provider
        _ = agent_id
        if not evidence_items:
            _last_citations.set([])
            return []

        valid = [link for evidence in evidence_items if (link := build_inline_link(evidence))]
        _last_citations.set(valid)
        return valid


def get_last_citations() -> list[str]:
    return _last_citations.get()
