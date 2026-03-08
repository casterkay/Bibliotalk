from __future__ import annotations

from datetime import UTC, datetime

from memory_page_service.resolver import ResolvedMemoryPage, parse_memory_page_id


def test_parse_memory_page_id_uses_user_and_compact_timestamp() -> None:
    user_id, timestamp = parse_memory_page_id("alan-watts_20260308T120000Z")

    assert user_id == "alan-watts"
    assert timestamp == datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC)


def test_resolved_memory_page_contract_shape() -> None:
    page = ResolvedMemoryPage(
        page_id="alan-watts_20260308T120000Z",
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        memory_item={"summary": "Discussed learning"},
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        video_url_with_timestamp="https://www.youtube.com/watch?v=abc123&t=60s",
        segment_text="Learning without thought is labor lost.",
    )

    assert page.memory_item["summary"] == "Discussed learning"
    assert page.video_url_with_timestamp.endswith("t=60s")
