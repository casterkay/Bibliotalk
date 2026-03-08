from __future__ import annotations

import uuid
from dataclasses import dataclass

from bt_common.evidence_store.models import Segment, TranscriptBatch
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class BatchingConfig:
    silence_gap_ms: int = 3_000
    char_limit: int = 1_800
    split_on_speaker_change: bool = True


@dataclass(frozen=True, slots=True)
class BatchSegment:
    seq: int
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    speaker_label: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedTranscriptBatch:
    speaker_label: str | None
    start_seq: int
    end_seq: int
    start_ms: int | None
    end_ms: int | None
    text: str
    batch_rule: str


def format_seq_label(start_ms: int | None) -> str:
    total_seconds = max((start_ms or 0) // 1000, 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"


def derive_transcript_batches(
    segments: list[BatchSegment],
    *,
    config: BatchingConfig | None = None,
) -> list[DerivedTranscriptBatch]:
    config = config or BatchingConfig()
    if not segments:
        return []

    ordered = sorted(segments, key=lambda segment: segment.seq)
    batches: list[DerivedTranscriptBatch] = []
    current: list[BatchSegment] = [ordered[0]]
    current_chars = len(ordered[0].text)

    def flush(rule: str) -> None:
        nonlocal current, current_chars
        if not current:
            return
        batches.append(
            DerivedTranscriptBatch(
                speaker_label=current[0].speaker_label,
                start_seq=current[0].seq,
                end_seq=current[-1].seq,
                start_ms=current[0].start_ms,
                end_ms=current[-1].end_ms,
                text="\n\n".join(segment.text for segment in current),
                batch_rule=rule,
            )
        )
        current = []
        current_chars = 0

    for segment in ordered[1:]:
        previous = current[-1]
        split_rule: str | None = None

        if (
            config.split_on_speaker_change
            and previous.speaker_label is not None
            and segment.speaker_label is not None
            and previous.speaker_label != segment.speaker_label
        ):
            split_rule = "speaker_change"
        elif previous.end_ms is not None and segment.start_ms is not None:
            if segment.start_ms - previous.end_ms > config.silence_gap_ms:
                split_rule = "silence_gap"

        if (
            split_rule is None
            and current_chars + 2 + len(segment.text) > config.char_limit
        ):
            split_rule = "char_limit"

        if split_rule is not None:
            flush(split_rule)
            current = [segment]
            current_chars = len(segment.text)
            continue

        current.append(segment)
        current_chars += 2 + len(segment.text)

    flush("char_limit")
    return batches


async def ensure_source_batches(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    config: BatchingConfig | None = None,
) -> list[TranscriptBatch]:
    existing = (
        (
            await session.execute(
                select(TranscriptBatch)
                .where(TranscriptBatch.source_id == source_id)
                .order_by(TranscriptBatch.start_seq, TranscriptBatch.batch_id)
            )
        )
        .scalars()
        .all()
    )
    if existing:
        return existing

    segments = (
        (
            await session.execute(
                select(Segment)
                .where(Segment.source_id == source_id, Segment.is_superseded.is_(False))
                .order_by(Segment.seq)
            )
        )
        .scalars()
        .all()
    )
    derived = derive_transcript_batches(
        [
            BatchSegment(
                seq=segment.seq,
                text=segment.text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker_label=None,
            )
            for segment in segments
        ],
        config=config,
    )
    if not derived:
        return []

    await session.execute(
        delete(TranscriptBatch).where(TranscriptBatch.source_id == source_id)
    )
    for batch in derived:
        session.add(
            TranscriptBatch(
                source_id=source_id,
                speaker_label=batch.speaker_label,
                start_seq=batch.start_seq,
                end_seq=batch.end_seq,
                start_ms=batch.start_ms,
                end_ms=batch.end_ms,
                text=batch.text,
                batch_rule=batch.batch_rule,
            )
        )
    await session.flush()
    return (
        (
            await session.execute(
                select(TranscriptBatch)
                .where(TranscriptBatch.source_id == source_id)
                .order_by(TranscriptBatch.start_seq, TranscriptBatch.batch_id)
            )
        )
        .scalars()
        .all()
    )
