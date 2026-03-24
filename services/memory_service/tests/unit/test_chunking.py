from __future__ import annotations

import re
from datetime import UTC, datetime

from memory_service.domain.models import Source, TranscriptLine
from memory_service.pipeline.chunking import chunk_plain_text, chunk_transcript


def test_chunk_plain_text_is_deterministic() -> None:
    src = Source(
        user_id="u1",
        external_id="e1",
        title="T",
        source_url="https://www.youtube.com/watch?v=e1",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    text = "Para 1 line.\n\nPara 2 line.\n\nPara 3 line."

    a = chunk_plain_text(src, text)
    b = chunk_plain_text(src, text)

    assert [s.message_id for s in a] == [s.message_id for s in b]
    assert [s.sha256 for s in a] == [s.sha256 for s in b]
    assert [s.text for s in a] == [s.text for s in b]


def test_chunk_transcript_merges_sentence_fragments_without_timestamp_prefix() -> None:
    src = Source(
        user_id="u1",
        external_id="vid1",
        title="Talk",
        source_url="https://www.youtube.com/watch?v=vid1",
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
    assert segments[0].create_time == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


def test_chunk_transcript_does_not_split_on_internal_punctuation() -> None:
    src = Source(
        user_id="u1",
        external_id="vid1",
        title="Talk",
        source_url="https://www.youtube.com/watch?v=vid1",
    )
    lines = [
        TranscriptLine(
            text=(
                "First sentence has enough words to create length pressure but ends properly. "
                "Second sentence should also remain complete when split. "
                "Third sentence ends cleanly."
            ),
            start_ms=0,
            end_ms=3000,
        )
    ]
    segments = chunk_transcript(src, lines)

    assert len(segments) == 1
    assert all(re.search(r'[.!?]["\')\]\u2019\u201D\uFF09\u3011]*$', s.text) for s in segments)
