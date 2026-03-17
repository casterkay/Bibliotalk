from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bt_common.evermemos_client import EverMemOSClient
from bt_store.models_core import Agent
from bt_store.models_evidence import Segment as StoredSegment
from bt_store.models_evidence import Source as StoredSource
from bt_store.models_ingestion import SourceIngestionState, SourceTextBatch
from sqlalchemy import delete, select

from ..domain.errors import IngestError
from ..domain.models import (
    IngestReport,
    ReportError,
    ReportSummary,
    SegmentResult,
    SourceContent,
    SourceResult,
)
from ..runtime.reporting import redact_text
from .chunking import ChunkingConfig, chunk_transcript, normalize_text
from .index import IngestionIndex

logger = logging.getLogger("memory_service")

# NOTE: `transcript_batches` are consumed by `discord_service` as message bodies.
# Discord messages have a hard 2000-character limit, and the rendered feed batch
# message prepends a `[HH:MM:SS]` label + newline.
_BATCH_CHAR_LIMIT = 1_800
_BATCH_SILENCE_GAP_MS = 15_000


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _default_segment_cache_dir() -> Path:
    return Path.cwd() / ".memory_service" / "segment_cache"


def _append_segment_cache_record(
    *,
    cache_dir: Path,
    user_id: str,
    payload: dict[str, Any],
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{user_id}.jsonl"

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _source_fingerprint(source_content: SourceContent) -> str:
    normalized = "\n".join(normalize_text(line.text) for line in source_content.content.lines)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _failed_source_result(
    *,
    source: Any,
    err: IngestError,
    redact_secrets: list[str],
    include_segment_details: bool,
) -> SourceResult:
    return SourceResult(
        user_id=source.user_id,
        platform=source.platform,
        external_id=source.external_id,
        title=source.title,
        source_url=getattr(source, "source_url", ""),
        group_id=source.group_id or "",
        status="failed",
        meta_saved=False,
        segments_total=0,
        segments_ingested=0,
        segments_skipped_unchanged=0,
        segments_failed=0,
        error=ReportError(code=err.code, message=redact_text(str(err), secrets=redact_secrets)),
        segments=[] if include_segment_details else None,
    )


def _derive_transcript_batches(segments: list[Any]) -> list[dict[str, Any]]:
    if not segments:
        return []

    batches: list[dict[str, Any]] = []
    current: list[Any] = [segments[0]]
    current_chars = len(segments[0].text)

    def flush(rule: str) -> None:
        nonlocal current, current_chars
        if not current:
            return
        batches.append(
            {
                "speaker_label": current[0].speaker,
                "start_seq": current[0].seq,
                "end_seq": current[-1].seq,
                "start_ms": current[0].start_ms,
                "end_ms": current[-1].end_ms,
                "text": "\n\n".join(segment.text for segment in current),
                "batch_rule": rule,
            }
        )
        current = []
        current_chars = 0

    for segment in segments[1:]:
        previous = current[-1]
        split_rule: str | None = None

        if previous.speaker != segment.speaker and (previous.speaker or segment.speaker):
            split_rule = "speaker_change"
        elif (
            previous.end_ms is not None
            and segment.start_ms is not None
            and segment.start_ms - previous.end_ms > _BATCH_SILENCE_GAP_MS
        ):
            split_rule = "silence_gap"
        elif current_chars + 2 + len(segment.text) > _BATCH_CHAR_LIMIT:
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


async def upsert_source_record(*, index: IngestionIndex, source: Any) -> StoredSource:
    async with index.session_factory() as session:
        agent = (
            await session.execute(select(Agent).where(Agent.slug == source.user_id))
        ).scalar_one_or_none()
        if agent is None:
            raise IngestError(f"Unknown agent slug: {source.user_id}", code="FIGURE_NOT_FOUND")

        stored = (
            await session.execute(
                select(StoredSource).where(
                    StoredSource.agent_id == agent.agent_id,
                    StoredSource.content_platform == source.platform,
                    StoredSource.external_id == source.external_id,
                )
            )
        ).scalar_one_or_none()
        if stored is None:
            stored = StoredSource(
                agent_id=agent.agent_id,
                content_platform=source.platform,
                external_id=source.external_id,
                emos_group_id=source.group_id or "",
                title=source.title,
                external_url=source.source_url,
            )
            session.add(stored)

        subscription_id = getattr(source, "subscription_id", None)
        if subscription_id is not None:
            stored.subscription_id = subscription_id
        stored.emos_group_id = source.group_id or stored.emos_group_id
        stored.title = source.title
        stored.external_url = source.source_url
        stored.channel_name = source.channel_name
        stored.published_at = source.published_at
        raw_meta = getattr(source, "raw_meta", None)
        if raw_meta:
            safe_meta: dict[str, Any]
            if isinstance(raw_meta, dict):
                try:
                    json.dumps(raw_meta, ensure_ascii=False)
                    safe_meta = raw_meta
                except TypeError:
                    safe_meta = {"raw_meta_error": "non_json_serializable"}
            else:
                safe_meta = {"raw_meta_error": f"expected_dict_got:{type(raw_meta).__name__}"}
            stored.raw_meta_json = safe_meta

        await session.flush()
        state = await session.get(SourceIngestionState, stored.source_id)
        if state is None:
            state = SourceIngestionState(source_id=stored.source_id)
            session.add(state)
        if state.ingest_status in {"failed", "no_transcript"}:
            state.ingest_status = "pending"

        await session.commit()
        await session.refresh(stored)
        return stored


async def _set_source_transcript_status(
    *,
    index: IngestionIndex,
    source_id: uuid.UUID,
    status: str,
) -> None:
    async with index.session_factory() as session:
        state = await session.get(SourceIngestionState, source_id)
        if state is None:
            state = SourceIngestionState(source_id=source_id)
            session.add(state)
        state.ingest_status = status
        if status == "ingested":
            state.failure_count = 0
            state.next_retry_at = None
            state.skip_reason = None
        state.updated_at = _now()
        await session.commit()


async def _delete_active_source_artifacts(*, index: IngestionIndex, source_id: uuid.UUID) -> None:
    async with index.session_factory() as session:
        await session.execute(delete(SourceTextBatch).where(SourceTextBatch.source_id == source_id))
        await session.execute(delete(StoredSegment).where(StoredSegment.source_id == source_id))
        await session.commit()


async def _persist_segment_record(
    *,
    index: IngestionIndex,
    source_id: uuid.UUID,
    agent_id: uuid.UUID,
    group_id: str,
    segment: Any,
) -> None:
    async with index.session_factory() as session:
        stored = (
            await session.execute(
                select(StoredSegment).where(
                    StoredSegment.source_id == source_id,
                    StoredSegment.seq == segment.seq,
                )
            )
        ).scalar_one_or_none()
        if stored is None:
            stored = StoredSegment(
                source_id=source_id,
                agent_id=agent_id,
                seq=segment.seq,
                text=segment.text,
                sha256=segment.sha256,
                emos_message_id=f"{group_id}:seg:{segment.seq}",
            )
            session.add(stored)

        stored.text = segment.text
        stored.sha256 = segment.sha256
        stored.start_ms = segment.start_ms
        stored.end_ms = segment.end_ms
        stored.create_time = segment.create_time
        stored.is_superseded = False
        await session.commit()


async def _replace_transcript_batches(
    *,
    index: IngestionIndex,
    source_id: uuid.UUID,
    segments: list[Any],
) -> None:
    batches = _derive_transcript_batches(segments)
    async with index.session_factory() as session:
        await session.execute(delete(SourceTextBatch).where(SourceTextBatch.source_id == source_id))
        for batch in batches:
            session.add(SourceTextBatch(source_id=source_id, **batch))
        await session.commit()


async def _prepare_manual_reingest(*, index: IngestionIndex, group_id: str) -> None:
    async with index.session_factory() as session:
        stored = (
            await session.execute(
                select(StoredSource).where(StoredSource.emos_group_id == group_id)
            )
        ).scalar_one_or_none()
        if stored is None:
            return

        state = await session.get(SourceIngestionState, stored.source_id)
        if state is None:
            state = SourceIngestionState(source_id=stored.source_id)
            session.add(state)
        state.ingest_status = "pending"
        state.manual_requested_at = None
        await session.execute(
            delete(SourceTextBatch).where(SourceTextBatch.source_id == stored.source_id)
        )
        await session.execute(
            delete(StoredSegment).where(StoredSegment.source_id == stored.source_id)
        )
        await session.commit()


async def _fail_ingest_and_cleanup(
    *,
    index: IngestionIndex,
    client: EverMemOSClient,
    source: Any,
    source_id: uuid.UUID,
) -> None:
    try:
        await client.delete_by_group_id(source.group_id or "", user_id=source.user_id)
    finally:
        await _delete_active_source_artifacts(index=index, source_id=source_id)
        await _set_source_transcript_status(index=index, source_id=source_id, status="failed")


async def ingest_source(
    *,
    source_content: SourceContent,
    index: IngestionIndex,
    client: EverMemOSClient,
    run_id: str | None = None,
    chunking_cfg: ChunkingConfig | None = None,
    include_segment_details: bool = True,
    redact_secrets: list[str] | None = None,
    segment_cache_dir: Path | None = None,
) -> SourceResult:
    redact_secrets = redact_secrets or []
    source = source_content.source
    default_group_id = source.group_id or ""
    default_group_name = source.title
    cache_dir = segment_cache_dir or _default_segment_cache_dir()

    segments = chunk_transcript(source, source_content.content.lines, cfg=chunking_cfg)
    try:
        stored_source = await upsert_source_record(index=index, source=source)
    except Exception as exc:
        err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
        return _failed_source_result(
            source=source,
            err=err,
            redact_secrets=redact_secrets,
            include_segment_details=include_segment_details,
        )

    if not segments:
        await _set_source_transcript_status(
            index=index,
            source_id=stored_source.source_id,
            status="no_transcript",
        )
        return SourceResult(
            user_id=source.user_id,
            platform=source.platform,
            external_id=source.external_id,
            title=source.title,
            source_url=source.source_url,
            group_id=default_group_id,
            status="failed",
            meta_saved=False,
            segments_total=0,
            segments_ingested=0,
            segments_skipped_unchanged=0,
            segments_failed=0,
            error=ReportError(code="NO_TRANSCRIPT", message="No transcript segments were produced"),
            segments=[] if include_segment_details else None,
        )

    # Ensure conversation metadata is saved for every conversation group used
    # by segments (for chapterized books this can be >1 group per source).
    group_meta: dict[str, str] = {}
    for seg in segments:
        gid = seg.group_id or default_group_id
        gname = default_group_name
        group_meta[gid] = gname
    if not group_meta:
        group_meta[default_group_id] = default_group_name

    meta_saved = False
    try:
        for gid, gname in group_meta.items():
            if await index.get_source_meta_saved(user_id=source.user_id, group_id=gid):
                continue
            meta = {
                "platform": source.platform,
                "external_id": source.external_id,
                "title": source.title,
                "group_name": gname,
                "source_url": source.source_url,
                "channel_name": source.channel_name,
                "published_at": (source.published_at.isoformat() if source.published_at else None),
                "raw_meta": source.raw_meta,
            }
            if gid != default_group_id:
                meta["conversation_type"] = "chapter"
                meta["parent_group_id"] = default_group_id
            await client.save_conversation_meta(
                group_id=gid,
                source_meta={k: v for k, v in meta.items() if v is not None},
            )
            await index.set_source_meta_saved(
                user_id=source.user_id,
                group_id=gid,
                source_fingerprint=_source_fingerprint(source_content),
            )
        meta_saved = True
    except Exception as exc:
        err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
        await _set_source_transcript_status(
            index=index,
            source_id=stored_source.source_id,
            status="failed",
        )
        return SourceResult(
            user_id=source.user_id,
            platform=source.platform,
            external_id=source.external_id,
            title=source.title,
            source_url=source.source_url,
            group_id=default_group_id,
            status="failed",
            meta_saved=False,
            segments_total=0,
            segments_ingested=0,
            segments_skipped_unchanged=0,
            segments_failed=0,
            error=ReportError(code=err.code, message=redact_text(str(err), secrets=redact_secrets)),
            segments=[] if include_segment_details else None,
        )

    seg_results: list[SegmentResult] = []
    ingested = 0
    skipped = 0
    failed = 0

    for seg in segments:
        seg_group_id = seg.group_id or default_group_id
        seg_group_name = default_group_name
        existing = await index.get_segment(user_id=source.user_id, message_id=seg.message_id)
        if existing and existing.sha256 == seg.sha256:
            skipped += 1
            if include_segment_details:
                seg_results.append(
                    SegmentResult(
                        seq=seg.seq,
                        message_id=seg.message_id,
                        sha256=seg.sha256,
                        status="skipped_unchanged",
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        create_time=seg.create_time,
                        group_id=seg_group_id,
                    )
                )
            continue

        try:
            logger.debug(
                "memorize run_id=%s group_id=%s message_id=%s seq=%s",
                run_id,
                seg_group_id,
                seg.message_id,
                seg.seq,
            )
            payload: dict[str, Any] = {
                "message_id": seg.message_id,
                "sender": source.user_id,
                "group_id": seg_group_id,
                "group_name": seg_group_name,
                "role": "assistant",
                "content": seg.text,
                "platform": source.platform,
                "external_id": source.external_id,
                "seq": seg.seq,
                "sha256": seg.sha256,
            }
            if source.source_url:
                payload["source_url"] = source.source_url
            if seg.start_ms is not None:
                payload["start_ms"] = seg.start_ms
            if seg.end_ms is not None:
                payload["end_ms"] = seg.end_ms
            if seg.create_time is not None:
                payload["create_time"] = seg.create_time.isoformat()
            if seg.speaker:
                payload["speaker"] = seg.speaker

            await client.memorize(payload)
            ingested += 1
            await _persist_segment_record(
                index=index,
                source_id=stored_source.source_id,
                agent_id=stored_source.agent_id,
                group_id=seg_group_id,
                segment=seg,
            )
            if include_segment_details:
                seg_results.append(
                    SegmentResult(
                        seq=seg.seq,
                        message_id=seg.message_id,
                        sha256=seg.sha256,
                        status="ingested",
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        create_time=seg.create_time,
                        group_id=seg_group_id,
                    )
                )
            try:
                _append_segment_cache_record(
                    cache_dir=cache_dir,
                    user_id=source.user_id,
                    payload=payload,
                )
            except Exception:
                logger.warning(
                    "segment cache write failed run_id=%s message_id=%s status=ingested",
                    run_id,
                    seg.message_id,
                )
        except Exception as exc:
            failed += 1
            err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
            if include_segment_details:
                seg_results.append(
                    SegmentResult(
                        seq=seg.seq,
                        message_id=seg.message_id,
                        sha256=seg.sha256,
                        status="failed",
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        create_time=seg.create_time,
                        group_id=seg_group_id,
                        error=ReportError(
                            code=err.code,
                            message=redact_text(str(err), secrets=redact_secrets),
                        ),
                    )
                )
            await _fail_ingest_and_cleanup(
                index=index,
                client=client,
                source=source,
                source_id=stored_source.source_id,
            )
            return SourceResult(
                user_id=source.user_id,
                platform=source.platform,
                external_id=source.external_id,
                title=source.title,
                source_url=source.source_url,
                group_id=default_group_id,
                status="failed",
                meta_saved=meta_saved,
                segments_total=len(segments),
                segments_ingested=ingested,
                segments_skipped_unchanged=skipped,
                segments_failed=failed,
                error=ReportError(code="SEGMENTS_FAILED", message=f"{failed} segments failed"),
                segments=seg_results if include_segment_details else None,
            )

    status = "done" if failed == 0 else "failed"
    error = None
    if failed:
        error = ReportError(code="SEGMENTS_FAILED", message=f"{failed} segments failed")
    else:
        await _replace_transcript_batches(
            index=index,
            source_id=stored_source.source_id,
            segments=segments,
        )
        await _set_source_transcript_status(
            index=index,
            source_id=stored_source.source_id,
            status="ingested",
        )

    return SourceResult(
        user_id=source.user_id,
        platform=source.platform,
        external_id=source.external_id,
        title=source.title,
        source_url=source.source_url,
        group_id=default_group_id,
        status=status,
        meta_saved=meta_saved,
        segments_total=len(segments),
        segments_ingested=ingested,
        segments_skipped_unchanged=skipped,
        segments_failed=failed,
        error=error,
        segments=seg_results if include_segment_details else None,
    )


async def manual_reingest_source(
    *,
    source_content: SourceContent,
    index: IngestionIndex,
    client: EverMemOSClient,
    run_id: str | None = None,
    chunking_cfg: ChunkingConfig | None = None,
    include_segment_details: bool = True,
    redact_secrets: list[str] | None = None,
    segment_cache_dir: Path | None = None,
) -> SourceResult:
    redact_secrets = redact_secrets or []
    source = source_content.source
    group_id = source.group_id or ""

    try:
        await client.delete_by_group_id(group_id, user_id=source.user_id)
        await _prepare_manual_reingest(index=index, group_id=group_id)
    except Exception as exc:
        err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
        return _failed_source_result(
            source=source,
            err=err,
            redact_secrets=redact_secrets,
            include_segment_details=include_segment_details,
        )

    return await ingest_source(
        source_content=source_content,
        index=index,
        client=client,
        run_id=run_id,
        chunking_cfg=chunking_cfg,
        include_segment_details=include_segment_details,
        redact_secrets=redact_secrets,
        segment_cache_dir=segment_cache_dir,
    )


async def ingest_sources(
    *,
    sources: list[SourceContent],
    index: IngestionIndex,
    client: EverMemOSClient,
    include_segment_details: bool = True,
    redact_secrets: list[str] | None = None,
    segment_cache_dir: Path | None = None,
) -> IngestReport:
    started = _now()
    run_id = str(uuid.uuid4())
    results: list[SourceResult] = []
    any_failed = False

    for item in sources:
        result = await ingest_source(
            source_content=item,
            index=index,
            client=client,
            run_id=run_id,
            include_segment_details=include_segment_details,
            redact_secrets=redact_secrets,
            segment_cache_dir=segment_cache_dir,
        )
        results.append(result)
        if result.status == "failed":
            any_failed = True

    summary = ReportSummary(
        sources_total=len(results),
        sources_succeeded=sum(1 for r in results if r.status == "done"),
        sources_failed=sum(1 for r in results if r.status == "failed"),
        segments_ingested=sum(r.segments_ingested for r in results),
        segments_skipped_unchanged=sum(r.segments_skipped_unchanged for r in results),
        segments_failed=sum(r.segments_failed for r in results),
    )
    finished = _now()

    return IngestReport(
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        status="failed" if any_failed else "done",
        summary=summary,
        sources=results,
    )
