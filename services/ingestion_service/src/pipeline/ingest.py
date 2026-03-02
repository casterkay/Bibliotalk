from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chunking import ChunkingConfig, chunk_plain_text, chunk_transcript, normalize_text
from .index import IngestionIndex
from .manifest import Manifest, ResolvedManifestSource, resolve_manifest_sources
from ..domain.errors import IngestError, InvalidInputError
from ..domain.models import (
    IngestReport,
    PlainTextContent,
    ReportError,
    ReportSummary,
    SegmentResult,
    SourceContent,
    SourceResult,
    TranscriptContent,
)
from ..runtime.reporting import redact_text
from bt_common.evermemos_client import EverMemOSClient

logger = logging.getLogger("ingestion_service")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _default_segment_cache_dir() -> Path:
    return Path.cwd() / ".ingestion_service" / "segment_cache"


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
    if isinstance(source_content.content, PlainTextContent):
        normalized = normalize_text(source_content.content.text)
    else:
        normalized = "\n".join(
            normalize_text(line.text) for line in source_content.content.lines
        )
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
        canonical_url=getattr(source, "canonical_url", None),
        group_id=source.group_id or "",
        status="failed",
        meta_saved=False,
        segments_total=0,
        segments_ingested=0,
        segments_skipped_unchanged=0,
        segments_failed=0,
        error=ReportError(
            code=err.code, message=redact_text(str(err), secrets=redact_secrets)
        ),
        segments=[] if include_segment_details else None,
    )


async def _source_content_from_resolved(
    resolved: ResolvedManifestSource,
) -> SourceContent:
    if resolved.mode == "text":
        if resolved.text is None:
            raise InvalidInputError("Manifest source mode=text missing text")
        return SourceContent(
            source=resolved.source, content=PlainTextContent(text=resolved.text)
        )

    if resolved.mode == "file":
        if resolved.file_path is None:
            raise InvalidInputError("Manifest source mode=file missing file_path")
        from ..adapters.local_text import load_file_source

        return load_file_source(
            user_id=resolved.source.user_id,
            platform=resolved.source.platform,
            external_id=resolved.source.external_id,
            title=resolved.source.title,
            path=resolved.file_path,
            canonical_url=resolved.source.canonical_url,
            author=resolved.source.author,
            published_at=(
                resolved.source.published_at.isoformat()
                if resolved.source.published_at
                else None
            ),
        )

    if resolved.mode == "gutenberg":
        if resolved.source.platform != "gutenberg":
            raise InvalidInputError("gutenberg_id requires platform=gutenberg")
        if resolved.gutenberg_id is None:
            raise InvalidInputError(
                "Manifest source mode=gutenberg missing gutenberg_id"
            )
        from ..adapters.gutenberg import load_gutenberg_source

        return await load_gutenberg_source(
            user_id=resolved.source.user_id,
            external_id=resolved.source.external_id,
            title=resolved.source.title,
            gutenberg_id=resolved.gutenberg_id,
            canonical_url=resolved.source.canonical_url,
            author=resolved.source.author,
        )

    if resolved.mode == "youtube":
        if resolved.source.platform != "youtube":
            raise InvalidInputError("youtube_video_id requires platform=youtube")
        if resolved.youtube_video_id is None:
            raise InvalidInputError(
                "Manifest source mode=youtube missing youtube_video_id"
            )
        from ..adapters.youtube_transcript import load_youtube_transcript_source

        return await load_youtube_transcript_source(
            user_id=resolved.source.user_id,
            external_id=resolved.source.external_id,
            title=resolved.source.title,
            video_id=resolved.youtube_video_id,
            canonical_url=resolved.source.canonical_url,
        )

    raise InvalidInputError(f"Unsupported manifest source mode: {resolved.mode}")


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
    default_group_name = source.group_name or source.title
    cache_dir = segment_cache_dir or _default_segment_cache_dir()

    if isinstance(source_content.content, PlainTextContent):
        segments = chunk_plain_text(
            source, source_content.content.text, cfg=chunking_cfg
        )
    else:
        segments = chunk_transcript(
            source, source_content.content.lines, cfg=chunking_cfg
        )

    # Ensure conversation metadata is saved for every conversation group used
    # by segments (for chapterized books this can be >1 group per source).
    group_meta: dict[str, str] = {}
    for seg in segments:
        gid = seg.group_id or default_group_id
        gname = seg.group_name or default_group_name
        group_meta[gid] = gname
    if not group_meta:
        group_meta[default_group_id] = default_group_name

    meta_saved = False
    try:
        for gid, gname in group_meta.items():
            if index.get_source_meta_saved(user_id=source.user_id, group_id=gid):
                continue
            meta = {
                "platform": source.platform,
                "external_id": source.external_id,
                "title": source.title,
                "group_name": gname,
                "canonical_url": source.canonical_url,
                "author": source.author,
                "published_at": (
                    source.published_at.isoformat() if source.published_at else None
                ),
                "raw_meta": source.raw_meta,
            }
            if gid != default_group_id:
                meta["conversation_type"] = "chapter"
                meta["parent_group_id"] = default_group_id
            await client.save_conversation_meta(
                group_id=gid,
                source_meta={k: v for k, v in meta.items() if v is not None},
            )
            index.set_source_meta_saved(
                user_id=source.user_id,
                group_id=gid,
                source_fingerprint=_source_fingerprint(source_content),
            )
        meta_saved = True
    except Exception as exc:  # noqa: BLE001
        err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
        return SourceResult(
            user_id=source.user_id,
            platform=source.platform,
            external_id=source.external_id,
            title=source.title,
            canonical_url=source.canonical_url,
            group_id=default_group_id,
            status="failed",
            meta_saved=False,
            segments_total=0,
            segments_ingested=0,
            segments_skipped_unchanged=0,
            segments_failed=0,
            error=ReportError(
                code=err.code, message=redact_text(str(err), secrets=redact_secrets)
            ),
            segments=[] if include_segment_details else None,
        )

    seg_results: list[SegmentResult] = []
    ingested = 0
    skipped = 0
    failed = 0

    for seg in segments:
        seg_group_id = seg.group_id or default_group_id
        seg_group_name = seg.group_name or default_group_name
        existing = index.get_segment(user_id=source.user_id, message_id=seg.message_id)
        if (
            existing
            and existing.sha256 == seg.sha256
            and existing.status in {"ingested", "skipped_unchanged"}
        ):
            skipped += 1
            index.upsert_segment_status(
                user_id=source.user_id,
                group_id=seg_group_id,
                message_id=seg.message_id,
                seq=seg.seq,
                sha256=seg.sha256,
                status="skipped_unchanged",
            )
            if include_segment_details:
                seg_results.append(
                    SegmentResult(
                        seq=seg.seq,
                        message_id=seg.message_id,
                        sha256=seg.sha256,
                        status="skipped_unchanged",
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        virtual_start_at=seg.virtual_start_at,
                        virtual_end_at=seg.virtual_end_at,
                        group_id=seg_group_id,
                        group_name=seg_group_name,
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
            if source.canonical_url:
                payload["canonical_url"] = source.canonical_url
            if seg.start_ms is not None:
                payload["start_ms"] = seg.start_ms
            if seg.end_ms is not None:
                payload["end_ms"] = seg.end_ms
            if seg.virtual_start_at:
                payload["virtual_start_at"] = seg.virtual_start_at
            if seg.virtual_end_at:
                payload["virtual_end_at"] = seg.virtual_end_at
            if seg.speaker:
                payload["speaker"] = seg.speaker

            await client.memorize(payload)
            ingested += 1
            index.upsert_segment_status(
                user_id=source.user_id,
                group_id=seg_group_id,
                message_id=seg.message_id,
                seq=seg.seq,
                sha256=seg.sha256,
                status="ingested",
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
                        virtual_start_at=seg.virtual_start_at,
                        virtual_end_at=seg.virtual_end_at,
                        group_id=seg_group_id,
                        group_name=seg_group_name,
                    )
                )
            try:
                _append_segment_cache_record(
                    cache_dir=cache_dir,
                    user_id=source.user_id,
                    payload=payload,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "segment cache write failed run_id=%s message_id=%s status=ingested",
                    run_id,
                    seg.message_id,
                )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
            index.upsert_segment_status(
                user_id=source.user_id,
                group_id=seg_group_id,
                message_id=seg.message_id,
                seq=seg.seq,
                sha256=seg.sha256,
                status="failed",
                error_code=err.code,
                error_message=redact_text(str(err), secrets=redact_secrets),
            )
            if include_segment_details:
                seg_results.append(
                    SegmentResult(
                        seq=seg.seq,
                        message_id=seg.message_id,
                        sha256=seg.sha256,
                        status="failed",
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        virtual_start_at=seg.virtual_start_at,
                        virtual_end_at=seg.virtual_end_at,
                        group_id=seg_group_id,
                        group_name=seg_group_name,
                        error=ReportError(
                            code=err.code,
                            message=redact_text(str(err), secrets=redact_secrets),
                        ),
                    )
                )

    status = "done" if failed == 0 else "failed"
    error = None
    if failed:
        error = ReportError(code="SEGMENTS_FAILED", message=f"{failed} segments failed")

    return SourceResult(
        user_id=source.user_id,
        platform=source.platform,
        external_id=source.external_id,
        title=source.title,
        canonical_url=source.canonical_url,
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


async def ingest_manifest(
    *,
    manifest: Manifest,
    index: IngestionIndex,
    client: EverMemOSClient,
    include_segment_details: bool = True,
    redact_secrets: list[str] | None = None,
    segment_cache_dir: Path | None = None,
) -> IngestReport:
    started = _now()
    run_id = str(uuid.uuid4())
    redact_secrets = redact_secrets or []

    results: list[SourceResult] = []
    any_failed = False

    for resolved in resolve_manifest_sources(manifest):
        try:
            source_content = await _source_content_from_resolved(resolved)
            result = await ingest_source(
                source_content=source_content,
                index=index,
                client=client,
                run_id=run_id,
                include_segment_details=include_segment_details,
                redact_secrets=redact_secrets,
                segment_cache_dir=segment_cache_dir,
            )
        except Exception as exc:  # noqa: BLE001
            err = exc if isinstance(exc, IngestError) else IngestError(str(exc))
            result = _failed_source_result(
                source=resolved.source,
                err=err,
                redact_secrets=redact_secrets,
                include_segment_details=include_segment_details,
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
