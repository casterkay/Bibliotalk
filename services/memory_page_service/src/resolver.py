from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from bt_common.evidence_store.models import Figure, Segment, Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def parse_memory_page_id(page_id: str) -> tuple[str, datetime]:
    user_id, _, timestamp_token = page_id.rpartition("_")
    if not user_id or not timestamp_token:
        raise ValueError("invalid memory page id")
    timestamp = datetime.strptime(timestamp_token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return user_id, timestamp


@dataclass(frozen=True, slots=True)
class ResolvedMemoryPage:
    page_id: str
    memory_user_id: str
    memory_timestamp: datetime
    memory_item: dict
    source_title: str
    source_url: str
    video_url_with_timestamp: str
    segment_text: str

    def to_dict(self) -> dict:
        return asdict(self)


class MemoryPageResolver:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, evermemos_client
    ):
        self._session_factory = session_factory
        self._client = evermemos_client

    async def resolve(self, page_id: str) -> ResolvedMemoryPage:
        user_id, timestamp = parse_memory_page_id(page_id)
        async with self._session_factory() as session:
            figure = await self._find_figure(session, user_id=user_id)
            if figure is None:
                raise LookupError(f"Unknown figure for memory page: {page_id}")
            row = (
                await session.execute(
                    select(Segment, Source)
                    .join(Source, Source.source_id == Segment.source_id)
                    .where(
                        Source.figure_id == figure.figure_id,
                        Segment.create_time == timestamp,
                    )
                )
            ).first()
        if row is None:
            raise LookupError(f"No local segment for memory page: {page_id}")
        segment, source = row
        memory_payload = await self._client.get_memories(
            user_id=user_id,
            memory_type="episodic_memory",
            start_time=timestamp.isoformat(),
            end_time=timestamp.isoformat(),
            limit=10,
        )
        memory_item = self._select_memory_item(
            memory_payload, user_id=user_id, timestamp=timestamp
        )
        if memory_item is None:
            raise LookupError(f"No EverMemOS memory for memory page: {page_id}")
        return ResolvedMemoryPage(
            page_id=page_id,
            memory_user_id=user_id,
            memory_timestamp=timestamp,
            memory_item=memory_item,
            source_title=source.title,
            source_url=source.source_url,
            video_url_with_timestamp=self._build_video_url(
                source=source, segment=segment
            ),
            segment_text=segment.text,
        )

    async def _find_figure(
        self, session: AsyncSession, *, user_id: str
    ) -> Figure | None:
        return (
            await session.execute(select(Figure).where(Figure.emos_user_id == user_id))
        ).scalar_one_or_none()

    def _select_memory_item(
        self,
        payload: dict,
        *,
        user_id: str,
        timestamp: datetime,
    ) -> dict | None:
        memories = payload.get("result", {}).get("memories", [])
        for item in memories:
            if item.get("user_id") != user_id:
                continue
            value = str(item.get("timestamp") or "").replace("Z", "+00:00")
            try:
                item_timestamp = datetime.fromisoformat(value)
            except ValueError:
                continue
            if item_timestamp == timestamp:
                return item
        return None

    def _build_video_url(self, *, source: Source, segment: Segment) -> str:
        offset = max(segment.start_ms or 0, 0) // 1000
        separator = "&" if "?" in source.source_url else "?"
        return f"{source.source_url}{separator}t={offset}s"
