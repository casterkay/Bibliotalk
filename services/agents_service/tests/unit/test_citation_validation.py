from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agents_service.models.citation import (
    NO_EVIDENCE_RESPONSE,
    Evidence,
    extract_memory_links,
    validate_evidence_links,
)


def test_validate_evidence_links_keeps_valid_inline_markdown_links() -> None:
    evidence = Evidence(
        segment_id=uuid4(),
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        text="Learning without thought is labor lost.",
        platform="youtube",
    )
    text = f"He said [Learning without thought is labor lost.]({evidence.memory_url})"

    validated = validate_evidence_links(text, [evidence], figure_emos_user_id="alan-watts")

    assert extract_memory_links(validated) == [
        ("Learning without thought is labor lost.", evidence.memory_url)
    ]


def test_validate_evidence_links_strips_invalid_links_to_plain_text() -> None:
    evidence = Evidence(
        segment_id=uuid4(),
        memory_user_id="confucius",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Analects",
        source_url="https://example.com",
        text="The superior man is modest in his speech.",
        platform="youtube",
    )
    text = f"Answer [The superior man is modest in his speech.]({evidence.memory_url})"

    validated = validate_evidence_links(text, [evidence], figure_emos_user_id="alan-watts")

    assert validated == "Answer The superior man is modest in his speech."
    assert NO_EVIDENCE_RESPONSE.endswith("question.")
