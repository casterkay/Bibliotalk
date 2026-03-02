from __future__ import annotations

from ingestion_service.domain.models import Source, TranscriptLine
from ingestion_service.pipeline.chunking import chunk_plain_text, chunk_transcript


def test_chunk_plain_text_is_deterministic() -> None:
    src = Source(user_id="u1", platform="local", external_id="e1", title="T")
    text = "Para 1 line.\n\nPara 2 line.\n\nPara 3 line."

    a = chunk_plain_text(src, text)
    b = chunk_plain_text(src, text)

    assert [s.message_id for s in a] == [s.message_id for s in b]
    assert [s.sha256 for s in a] == [s.sha256 for s in b]
    assert [s.text for s in a] == [s.text for s in b]


def test_chunk_transcript_merges_sentence_fragments_without_timestamp_prefix() -> None:
    src = Source(
        user_id="u1",
        platform="youtube",
        external_id="vid1",
        title="Talk",
        raw_meta={"timestamp": 1700000000},
    )
    lines = [
        TranscriptLine(text="This is a fragmented", start_ms=0, end_ms=600),
        TranscriptLine(text="sentence.", start_ms=600, end_ms=1100),
        TranscriptLine(text="And another one", start_ms=1300, end_ms=1800),
        TranscriptLine(text="ends here!", start_ms=1800, end_ms=2300),
    ]
    segments = chunk_transcript(src, lines)

    assert [s.text for s in segments] == [
        "This is a fragmented sentence.",
        "And another one ends here!",
    ]
    assert all(not s.text.startswith("[") for s in segments)
    assert segments[0].virtual_start_at == "2023-11-14T22:13:20Z"
    assert segments[0].virtual_end_at == "2023-11-14T22:13:21Z"


def test_chunk_plain_text_gutenberg_chapter_conversations() -> None:
    src = Source(user_id="u1", platform="gutenberg", external_id="3330", title="Analects")
    text = (
        "CHAPTER I\n\n"
        "Paragraph one.\n\n"
        "Paragraph two.\n\n"
        "CHAPTER II\n\n"
        "Paragraph three."
    )
    segments = chunk_plain_text(src, text)
    assert len(segments) == 3
    assert len({s.group_id for s in segments}) == 2
    assert all(s.group_id for s in segments)
