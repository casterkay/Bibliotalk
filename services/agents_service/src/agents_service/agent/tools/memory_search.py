"""Memory search tool: EMOS retrieve + local rerank + Evidence mapping."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from ...models.citation import Evidence
from ...models.segment import Segment, bm25_rerank

SourcesByGroupIdsProvider = Callable[[list[str]], Awaitable[list[dict[str, Any]]]]
SegmentsBySourceIdsProvider = Callable[[list[str]], Awaitable[list[dict[str, Any]]]]
SegmentsForAgentProvider = Callable[[str], Awaitable[list[dict[str, Any]]]]


def _extract_query_terms(search_payload: dict[str, Any]) -> list[str]:
    result = search_payload.get("result", {})
    memories = result.get("memories", [])
    terms: list[str] = []
    for memory_group in memories:
        for entries in memory_group.values():
            for item in entries:
                summary = item.get("summary")
                if summary:
                    terms.append(summary)
    return terms


def _extract_memory_items(search_payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = search_payload.get("result", {})
    memories = result.get("memories", [])
    items: list[dict[str, Any]] = []
    for memory_group in memories:
        for entries in memory_group.values():
            for item in entries:
                if isinstance(item, dict):
                    items.append(item)
    return items


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _extract_group_ids(search_payload: dict[str, Any]) -> list[str]:
    result = search_payload.get("result", {})
    memories = result.get("memories", [])
    group_ids: list[str] = []
    for memory_group in memories:
        for entries in memory_group.values():
            for item in entries:
                group_id = item.get("group_id")
                if isinstance(group_id, str) and group_id:
                    group_ids.append(group_id)
    # Keep stable order but unique.
    seen: set[str] = set()
    unique: list[str] = []
    for gid in group_ids:
        if gid in seen:
            continue
        seen.add(gid)
        unique.append(gid)
    return unique


class MemorySearchTool:
    def __init__(
        self,
        *,
        evermemos_client: Any,
        sources_by_group_ids_provider: SourcesByGroupIdsProvider,
        segments_by_source_ids_provider: SegmentsBySourceIdsProvider,
        segments_for_agent_provider: SegmentsForAgentProvider,
        top_k: int = 8,
    ):
        self.evermemos_client = evermemos_client
        self.sources_by_group_ids_provider = sources_by_group_ids_provider
        self.segments_by_source_ids_provider = segments_by_source_ids_provider
        self.segments_for_agent_provider = segments_for_agent_provider
        self.top_k = top_k

    async def __call__(self, query: str, agent_id: str) -> list[Evidence]:
        # Step 1: RRF retrieve (fast).
        search_result = await self.evermemos_client.search(
            query,
            user_id=agent_id,
            retrieve_method="rrf",
            top_k=self.top_k,
        )
        group_ids = _extract_group_ids(search_result)

        # Step 2: Agentic fallback if RRF didn't find enough sources.
        if len(group_ids) < 3:
            search_result = await self.evermemos_client.search(
                query,
                user_id=agent_id,
                retrieve_method="agentic",
                top_k=self.top_k,
            )
            group_ids = _extract_group_ids(search_result)

        memory_items = _extract_memory_items(search_result)
        memory_items_by_group_id: dict[str, list[dict[str, Any]]] = {}
        for item in memory_items:
            group_id = item.get("group_id")
            if isinstance(group_id, str) and group_id:
                memory_items_by_group_id.setdefault(group_id, []).append(item)

        # Step 3: Narrow candidates using group_ids → sources → segments.
        segment_rows: list[dict[str, Any]] = []
        sources_by_id: dict[str, dict[str, Any]] = {}
        if group_ids:
            source_rows = await _maybe_await(self.sources_by_group_ids_provider(group_ids))
            sources_by_id = {str(row.get("id")): row for row in source_rows if row.get("id")}
            source_ids = [str(row["id"]) for row in source_rows if row.get("id")]
            if source_ids:
                segment_rows = await _maybe_await(self.segments_by_source_ids_provider(source_ids))

        # Fallback: if the narrowing produced nothing, avoid "search everything" unless
        # explicitly desired. Return empty evidence so the Spirit can say it has no evidence.
        if not segment_rows:
            return []

        segments = [Segment.model_validate(row) for row in segment_rows]
        query_terms = " ".join(_extract_query_terms(search_result))
        ranking_query = query_terms or query
        reranked = bm25_rerank(ranking_query, segments, top_k=self.top_k)

        row_by_segment_id: dict[str, dict[str, Any]] = {}
        for row in segment_rows:
            segment_id = row.get("id")
            if segment_id is not None:
                row_by_segment_id[str(segment_id)] = row

        evidences: list[Evidence] = []
        for segment in reranked:
            row = row_by_segment_id.get(str(segment.id)) or {}
            source_row = sources_by_id.get(str(row.get("source_id"))) or {}
            memory_user_id = str(
                row.get("memory_user_id") or source_row.get("memory_user_id") or agent_id
            )
            memory_timestamp = _parse_timestamp(row.get("create_time"))
            group_id = str(row.get("group_id") or source_row.get("emos_group_id") or "")

            memory_item = None
            for candidate in memory_items_by_group_id.get(group_id, []):
                candidate_timestamp = _parse_timestamp(candidate.get("timestamp"))
                if memory_timestamp is not None and candidate_timestamp == memory_timestamp:
                    memory_item = candidate
                    break
            if memory_item is None and memory_items_by_group_id.get(group_id):
                memory_item = memory_items_by_group_id[group_id][0]
            if memory_item is not None:
                memory_user_id = str(memory_item.get("user_id") or memory_user_id)
                memory_timestamp = (
                    _parse_timestamp(memory_item.get("timestamp")) or memory_timestamp
                )

            source_title = row.get("source_title") or source_row.get("title") or "Unknown Source"
            source_url = row.get("source_url") or source_row.get("external_url") or ""
            evidences.append(
                Evidence(
                    segment_id=segment.id,
                    source_id=segment.source_id,
                    agent_id=segment.agent_id,
                    memory_user_id=memory_user_id,
                    memory_timestamp=memory_timestamp,
                    emos_message_id=segment.emos_message_id,
                    source_title=str(source_title),
                    source_url=str(source_url),
                    text=segment.text,
                    group_id=group_id,
                    platform=segment.platform,
                    published_at=_parse_timestamp(row.get("published_at"))
                    or _parse_timestamp(source_row.get("published_at")),
                )
            )

        return evidences
