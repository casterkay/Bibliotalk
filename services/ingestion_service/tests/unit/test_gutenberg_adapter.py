from __future__ import annotations

from ingestion_service.adapters.gutenberg import _normalize_linebreaks, _strip_gutenberg_boilerplate


def test_strip_gutenberg_boilerplate() -> None:
    raw = (
        "Header\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
        "Line A\n"
        "Line B\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
        "Footer\n"
    )
    assert _strip_gutenberg_boilerplate(raw) == "Line A\nLine B"


def test_normalize_linebreaks_keeps_paragraph_boundaries() -> None:
    raw = (
        "This is line one\n"
        "line two in same paragraph\n"
        "\n"
        "CHAPTER I\n"
        "\n"
        "Next paragraph\n"
        "continues here\n"
    )
    normalized = _normalize_linebreaks(raw)
    assert normalized == (
        "This is line one line two in same paragraph\n\n"
        "CHAPTER I\n\n"
        "Next paragraph continues here"
    )

