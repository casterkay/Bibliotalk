from __future__ import annotations

from discord_service.feed.batcher import (
    BatchingConfig,
    BatchSegment,
    derive_transcript_batches,
    format_seq_label,
)


def test_batcher_splits_on_silence_gap() -> None:
    batches = derive_transcript_batches(
        [
            BatchSegment(seq=0, text="First line.", start_ms=0, end_ms=1000),
            BatchSegment(seq=1, text="Still same thought.", start_ms=1200, end_ms=2200),
            BatchSegment(seq=2, text="New paragraph.", start_ms=7000, end_ms=8200),
        ]
    )

    assert [
        (batch.start_seq, batch.end_seq, batch.batch_rule) for batch in batches
    ] == [
        (0, 1, "silence_gap"),
        (2, 2, "char_limit"),
    ]


def test_batcher_splits_on_speaker_change_when_both_labels_present() -> None:
    batches = derive_transcript_batches(
        [
            BatchSegment(
                seq=0, text="Question.", start_ms=0, end_ms=1000, speaker_label="Host"
            ),
            BatchSegment(
                seq=1, text="Answer.", start_ms=1200, end_ms=2000, speaker_label="Guest"
            ),
        ]
    )

    assert [
        (batch.start_seq, batch.end_seq, batch.batch_rule) for batch in batches
    ] == [
        (0, 0, "speaker_change"),
        (1, 1, "char_limit"),
    ]


def test_batcher_falls_back_to_char_limit_without_timing_metadata() -> None:
    batches = derive_transcript_batches(
        [
            BatchSegment(seq=0, text="a" * 20),
            BatchSegment(seq=1, text="b" * 20),
            BatchSegment(seq=2, text="c" * 20),
        ],
        config=BatchingConfig(char_limit=45),
    )

    assert [
        (batch.start_seq, batch.end_seq, batch.batch_rule) for batch in batches
    ] == [
        (0, 1, "char_limit"),
        (2, 2, "char_limit"),
    ]
    assert format_seq_label(83_000) == "[00:01:23]"
