from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from bt_common.config import get_settings
from agents_service.models.citation import (
    Evidence,
    build_inline_link,
    extract_memory_links,
    validate_evidence_links,
)


def test_evidence_construction_derives_memory_url_and_video_timestamp_link() -> None:
    evidence = Evidence(
        segment_id=uuid4(),
        source_id=uuid4(),
        agent_id=uuid4(),
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        text="Learning without thought is labor lost.",
        group_id="alan-watts:youtube:abc123",
        platform="youtube",
        published_at=datetime(2026, 3, 8, 11, 59, 0, tzinfo=UTC),
    )

    assert (
        evidence.memory_url == "https://www.bibliotalk.space/memories/alan-watts_20260308T120000Z"
    )
    assert evidence.video_url_with_timestamp == "https://www.youtube.com/watch?v=abc123&t=60s"
    assert (
        build_inline_link(evidence)
        == "[Learning without thought is labor lost.](https://www.bibliotalk.space/memories/alan-watts_20260308T120000Z)"
    )


def test_validate_evidence_links_strips_cross_figure_and_bad_quotes() -> None:
    evidence = Evidence(
        segment_id=uuid4(),
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        text="Learning without thought is labor lost.",
        platform="youtube",
    )
    valid = validate_evidence_links(
        f"Answer [Learning without thought is labor lost.]({evidence.memory_url})",
        [evidence],
        agent_emos_user_id="alan-watts",
    )
    invalid = validate_evidence_links(
        f"Answer [Fabricated quote]({evidence.memory_url})",
        [evidence],
        agent_emos_user_id="alan-watts",
    )

    assert extract_memory_links(valid) == [
        ("Learning without thought is labor lost.", evidence.memory_url)
    ]
    assert extract_memory_links(invalid) == []


def test_evidence_construction_respects_configured_public_base_url(monkeypatch) -> None:
    monkeypatch.setenv("BIBLIOTALK_WEB_URL", "https://example.test")
    get_settings.cache_clear()
    try:
        evidence = Evidence(
            segment_id=uuid4(),
            source_id=uuid4(),
            agent_id=uuid4(),
            memory_user_id="alan-watts",
            memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
            source_title="Alan Watts Lecture",
            source_url="https://www.youtube.com/watch?v=abc123",
            text="Learning without thought is labor lost.",
            group_id="alan-watts:youtube:abc123",
            platform="youtube",
        )
        assert evidence.memory_url == "https://example.test/memories/alan-watts_20260308T120000Z"
    finally:
        get_settings.cache_clear()
