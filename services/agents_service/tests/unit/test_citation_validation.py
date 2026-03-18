from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agents_service.models.citation import (
    NO_EVIDENCE_RESPONSE,
    Evidence,
    build_inline_link,
    build_verifiable_quote,
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

    validated = validate_evidence_links(text, [evidence], agent_emos_user_id="alan-watts")

    assert extract_memory_links(validated) == [
        ("Learning without thought is labor lost.", evidence.memory_url)
    ]


def test_validate_evidence_links_allows_whitespace_normalized_visible_text() -> None:
    evidence = Evidence(
        segment_id=uuid4(),
        memory_user_id="alan-watts",
        memory_timestamp=datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC),
        source_title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        text="Learning without thought\nis  labor\tlost.",
        platform="youtube",
    )
    link = build_inline_link(evidence)
    assert link is not None

    validated = validate_evidence_links(
        f"He said {link}",
        [evidence],
        agent_emos_user_id="alan-watts",
    )

    assert extract_memory_links(validated) == [
        ("Learning without thought is labor lost.", evidence.memory_url)
    ]


def test_build_verifiable_quote_returns_verifiable_single_line_substring() -> None:
    raw = "  First line.\nSecond line.  "
    quote = build_verifiable_quote(raw, max_chars=200)

    assert quote == "First line."
    assert quote in raw


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

    validated = validate_evidence_links(text, [evidence], agent_emos_user_id="alan-watts")

    assert validated == "Answer The superior man is modest in his speech."
    assert NO_EVIDENCE_RESPONSE.endswith("question.")
