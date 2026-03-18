from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bt_common.evermemos_client import EverMemOSClient

from .memcell_split import parse_emos_timestamp, split_chunks_by_memcell_timestamps
from .memories_store import MemoriesStore, StoredChunk, StoredSource
from .memory_id import format_memory_id, parse_memory_id


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _extract_get_memories_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result", {})
    memories = result.get("memories", [])
    return [item for item in memories if isinstance(item, dict)]


def _extract_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result", {})
    memories = result.get("memories", [])
    items: list[dict[str, Any]] = []
    for memory_group in memories:
        if not isinstance(memory_group, dict):
            continue
        for entries in memory_group.values():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if isinstance(item, dict):
                    items.append(item)
    return items


@dataclass(frozen=True, slots=True)
class MemCellView:
    memory_id: str
    agent_slug: str
    source: StoredSource
    timestamp: datetime
    memcell: dict[str, Any]
    chunks: list[StoredChunk]


class MemoriesService:
    def __init__(
        self,
        *,
        store: MemoriesStore,
        evermemos_client: EverMemOSClient,
        public_base_url: str,
    ):
        self._store = store
        self._emos = evermemos_client
        self._public_base_url = public_base_url.rstrip("/")

    async def resolve_memory_id(self, memory_id: str) -> tuple[str, dict[str, Any]]:
        agent_slug, timestamp = parse_memory_id(memory_id)
        payload = await self._emos.get_memories(
            user_id=agent_slug,
            memory_type="episodic_memory",
            start_time=timestamp.isoformat(),
            end_time=timestamp.isoformat(),
            limit=100,
        )
        candidates = []
        for item in _extract_get_memories_items(payload):
            item_ts = parse_emos_timestamp(item.get("timestamp"))
            if item_ts == _ensure_utc(timestamp):
                candidates.append(item)
        if not candidates:
            raise LookupError(f"Unknown memory id: {memory_id}")
        if len(candidates) > 1:
            group_ids = sorted(
                {str(item.get("group_id") or "") for item in candidates if item.get("group_id")}
            )
            raise LookupError(
                f"Ambiguous memory id (multiple sources at same timestamp). Use `source_id=`. sources={group_ids}"
            )
        item = candidates[0]
        source_id = str(item.get("group_id") or "")
        if not source_id:
            raise LookupError(f"EverMemOS memory missing group_id for: {memory_id}")
        return source_id, item

    async def list_source_memcells(
        self, *, source_id: str, limit: int, offset: int
    ) -> list[MemCellView]:
        source = await self._store.get_source_by_source_id(source_id)
        if source is None:
            raise LookupError(f"Unknown source_id: {source_id}")

        memcells = await self._fetch_memcells_for_source(source_id)
        memcells.sort(
            key=lambda item: parse_emos_timestamp(item.get("timestamp"))
            or datetime.min.replace(tzinfo=UTC)
        )

        chunks = await self._store.list_chunks_for_source(source_id)
        if not chunks:
            return []
        chunk_times = [c.timestamp for c in chunks]

        timestamps: list[datetime] = []
        normalized_cells: list[tuple[datetime, dict[str, Any]]] = []
        for item in memcells:
            ts = parse_emos_timestamp(item.get("timestamp"))
            if ts is None:
                continue
            timestamps.append(ts)
            normalized_cells.append((ts, item))

        ranges = split_chunks_by_memcell_timestamps(
            chunk_timestamps=chunk_times, memcell_timestamps=timestamps
        )
        views: list[MemCellView] = []
        for (ts, item), (start, end) in zip(normalized_cells, ranges, strict=False):
            memory_id = format_memory_id(agent_slug=source.agent_slug, timestamp=ts)
            views.append(
                MemCellView(
                    memory_id=memory_id,
                    agent_slug=source.agent_slug,
                    source=source,
                    timestamp=ts,
                    memcell=item,
                    chunks=chunks[start:end],
                )
            )

        # Apply paging after building views (stable for MVP).
        offset = max(0, int(offset))
        limit = max(0, int(limit))
        return views[offset : offset + limit]

    async def get_memcell_view_by_id(self, memory_id: str) -> MemCellView:
        source_id, memcell_item = await self.resolve_memory_id(memory_id)
        views = await self.list_source_memcells(source_id=source_id, limit=5_000, offset=0)
        _, ts = parse_memory_id(memory_id)
        target = _ensure_utc(ts)
        for view in views:
            if _ensure_utc(view.timestamp) == target:
                # Replace memcell with the exact object we resolved (to keep raw fields).
                return MemCellView(
                    memory_id=view.memory_id,
                    agent_slug=view.agent_slug,
                    source=view.source,
                    timestamp=view.timestamp,
                    memcell=memcell_item,
                    chunks=view.chunks,
                )
        raise LookupError(f"Unknown memory id for source: {memory_id}")

    async def search(
        self,
        *,
        agent_slug: str,
        query: str,
        retrieve_method: str,
        top_k: int,
    ) -> list[MemCellView]:
        payload = await self._emos.search(
            query,
            user_id=agent_slug,
            retrieve_method=retrieve_method,
            top_k=top_k,
            memory_types=["episodic_memory"],
        )
        items = _extract_search_items(payload)
        by_source: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            gid = item.get("group_id")
            if isinstance(gid, str) and gid:
                by_source.setdefault(gid, []).append(item)

        views: list[MemCellView] = []
        for source_id, cell_items in by_source.items():
            # Build a full mapping for this source once, then pick the cells used by search.
            source_views = await self.list_source_memcells(
                source_id=source_id, limit=5_000, offset=0
            )
            view_by_ts = {_ensure_utc(v.timestamp): v for v in source_views}
            for item in cell_items:
                ts = parse_emos_timestamp(item.get("timestamp"))
                if ts is None:
                    continue
                view = view_by_ts.get(_ensure_utc(ts))
                if view is None:
                    continue
                views.append(
                    MemCellView(
                        memory_id=view.memory_id,
                        agent_slug=view.agent_slug,
                        source=view.source,
                        timestamp=view.timestamp,
                        memcell=item,
                        chunks=view.chunks,
                    )
                )

        # Deterministic order: earliest-to-latest in returned set.
        views.sort(key=lambda v: _ensure_utc(v.timestamp))
        # Trim to top_k (search may return duplicates).
        return views[: max(1, int(top_k))]

    def build_links(self, view: MemCellView) -> dict[str, str | None]:
        html = f"{self._public_base_url}/memories/{view.memory_id}"
        video_link = None
        if (
            view.source.platform == "youtube"
            and view.source.url
            and view.source.published_at is not None
        ):
            offset_s = max(
                0,
                int(
                    math.floor(
                        (
                            _ensure_utc(view.timestamp) - _ensure_utc(view.source.published_at)
                        ).total_seconds()
                    )
                ),
            )
            separator = "&" if "?" in view.source.url else "?"
            video_link = f"{view.source.url}{separator}t={offset_s}s"
        return {"html": html, "video_at_timepoint": video_link}

    async def _fetch_memcells_for_source(self, source_id: str) -> list[dict[str, Any]]:
        # Paged fetch in case a source has many cells.
        items: list[dict[str, Any]] = []
        offset = 0
        limit = 200
        while True:
            payload = await self._emos.get_memories(
                group_id=source_id,
                memory_type="episodic_memory",
                limit=limit,
                offset=offset,
            )
            page = _extract_get_memories_items(payload)
            if not page:
                break
            items.extend(page)
            result = payload.get("result", {})
            has_more = bool(result.get("has_more"))
            offset += limit
            if not has_more:
                break
            if offset > 5_000:
                break
        return items
