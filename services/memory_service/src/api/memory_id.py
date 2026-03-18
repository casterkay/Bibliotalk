from __future__ import annotations

from datetime import UTC, datetime


def parse_memory_id(memory_id: str) -> tuple[str, datetime]:
    agent_slug, _, timestamp_token = memory_id.rpartition("_")
    if not agent_slug or not timestamp_token:
        raise ValueError("invalid memory id")
    timestamp = datetime.strptime(timestamp_token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return agent_slug, timestamp


def format_memory_id(*, agent_slug: str, timestamp: datetime) -> str:
    ts = timestamp.astimezone(UTC) if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    return f"{agent_slug}_{ts.strftime('%Y%m%dT%H%M%SZ')}"
