from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, datetime
from typing import Any


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_emos_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _ensure_utc(parsed)


def split_chunks_by_memcell_timestamps(
    *,
    chunk_timestamps: list[datetime],
    memcell_timestamps: list[datetime],
) -> list[tuple[int, int]]:
    """Return ranges [start, end) into `chunk_timestamps` for each memcell boundary.

    Cell i is (t{i-1}, t{i}] inclusive on end boundary. This function assumes both sequences
    are in ascending time order.
    """

    if not memcell_timestamps:
        return []
    boundaries = [_ensure_utc(t) for t in memcell_timestamps]
    chunk_times = [_ensure_utc(t) for t in chunk_timestamps]

    ends: list[int] = [bisect_right(chunk_times, boundary) for boundary in boundaries]
    ranges: list[tuple[int, int]] = []
    start = 0
    for end in ends:
        ranges.append((start, end))
        start = end
    return ranges
