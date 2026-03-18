from __future__ import annotations

from datetime import UTC, datetime

from memory_service.api.memory_id import format_memory_id, parse_memory_id


def test_parse_and_format_memory_id_roundtrip() -> None:
    agent_slug = "alan-watts"
    ts = datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC)

    memory_id = format_memory_id(agent_slug=agent_slug, timestamp=ts)
    parsed_slug, parsed_ts = parse_memory_id(memory_id)

    assert memory_id == "alan-watts_20260308T120000Z"
    assert parsed_slug == agent_slug
    assert parsed_ts == ts
