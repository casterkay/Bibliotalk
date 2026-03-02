from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..domain.models import Segment, Source, TranscriptLine, build_segment


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.lstrip("\ufeff")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    target_chars: int = 1200
    max_chars: int = 1500


@dataclass(frozen=True, slots=True)
class _TranscriptMessage:
    text: str
    start_ms: int | None
    end_ms: int | None
    speaker: str | None


_PARA_SPLIT_RE = re.compile(r"\n\s*\n+")
_CHAPTER_HEADING_RE = re.compile(
    r"^(chapter|book|part|section)\s+([ivxlcdm]+|\d+)\b.*$",
    flags=re.IGNORECASE,
)
_SENTENCE_END_RE = re.compile(r'[.!?。！？]["\')\]’”）】]*$')


def _split_long(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining.strip())
            break
        cut = remaining.rfind(" ", 0, max_chars + 1)
        if cut < max_chars * 0.6:
            cut = max_chars
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [p for p in parts if p]


def _looks_like_chapter_heading(paragraph: str) -> bool:
    collapsed = " ".join(paragraph.split())
    if not collapsed or len(collapsed) > 120:
        return False
    if _CHAPTER_HEADING_RE.match(collapsed):
        return True
    if collapsed.isupper() and 1 <= len(collapsed.split()) <= 10:
        return True
    return False


def _chapterized_paragraphs(paragraphs: list[str]) -> list[tuple[str, str]]:
    chapter_title = "Main Text"
    chapter_buckets: list[tuple[str, list[str]]] = [(chapter_title, [])]
    seen_titles = {chapter_title}

    for paragraph in paragraphs:
        if _looks_like_chapter_heading(paragraph):
            title = " ".join(paragraph.split())
            if title in seen_titles:
                continue
            seen_titles.add(title)
            chapter_buckets.append((title, []))
            continue
        chapter_buckets[-1][1].append(paragraph)

    out: list[tuple[str, str]] = []
    for title, paras in chapter_buckets:
        if not paras:
            continue
        out.append((title, "\n\n".join(paras)))
    return out


def _chunk_plain_text_default(source: Source, text: str, cfg: ChunkingConfig) -> list[Segment]:
    paragraphs = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    packed: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if not buf:
            return
        packed.append("\n\n".join(buf).strip())
        buf = []
        buf_len = 0

    for para in paragraphs:
        for para_piece in _split_long(para, cfg.max_chars):
            piece_len = len(para_piece)
            if not buf:
                buf = [para_piece]
                buf_len = piece_len
                continue
            if buf_len + 2 + piece_len <= cfg.max_chars:
                buf.append(para_piece)
                buf_len += 2 + piece_len
            else:
                flush()
                buf = [para_piece]
                buf_len = piece_len

            if buf_len >= cfg.target_chars:
                flush()

    flush()
    segments: list[Segment] = []
    for seq, seg_text in enumerate(packed):
        segments.append(
            build_segment(
                source=source,
                seq=seq,
                text=seg_text.strip(),
                sha256=sha256_text(seg_text.strip()),
                start_ms=None,
                end_ms=None,
                speaker=None,
            )
        )
    return segments


def _chunk_plain_text_gutenberg(source: Source, text: str, cfg: ChunkingConfig) -> list[Segment]:
    paragraphs = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    chapter_blocks = _chapterized_paragraphs(paragraphs)
    if not chapter_blocks:
        return []

    segments: list[Segment] = []
    chapter_count = len(chapter_blocks)
    for chapter_idx, (chapter_title, chapter_text) in enumerate(chapter_blocks, start=1):
        chapter_group_id = f"{source.group_id}:chapter:{chapter_idx:03d}"
        chapter_group_name = f"{source.title} — {chapter_title}"

        for paragraph in [p.strip() for p in _PARA_SPLIT_RE.split(chapter_text) if p.strip()]:
            # Gutenberg paragraphs are treated as message boundaries.
            for piece in _split_long(paragraph, cfg.max_chars):
                piece = piece.strip()
                segments.append(
                    build_segment(
                        source=source,
                        seq=len(segments),
                        text=piece,
                        sha256=sha256_text(piece),
                        start_ms=None,
                        end_ms=None,
                        speaker=None,
                        group_id=chapter_group_id,
                        group_name=(
                            f"{chapter_group_name} "
                            f"({chapter_idx}/{chapter_count})"
                        ),
                    )
                )
    return segments


def chunk_plain_text(source: Source, text: str, *, cfg: ChunkingConfig | None = None) -> list[Segment]:
    cfg = cfg or ChunkingConfig()
    normalized = normalize_text(text)
    if not normalized:
        return []
    if source.platform == "gutenberg":
        return _chunk_plain_text_gutenberg(source, normalized, cfg)
    return _chunk_plain_text_default(source, normalized, cfg)


def _merge_transcript_messages(lines: list[TranscriptLine], cfg: ChunkingConfig) -> list[_TranscriptMessage]:
    messages: list[_TranscriptMessage] = []
    cur_text_parts: list[str] = []
    cur_start: int | None = None
    cur_end: int | None = None
    cur_speaker: str | None = None

    def flush() -> None:
        nonlocal cur_text_parts, cur_start, cur_end, cur_speaker
        if not cur_text_parts:
            return
        merged = " ".join(part.strip() for part in cur_text_parts if part.strip()).strip()
        if merged:
            messages.append(
                _TranscriptMessage(
                    text=merged,
                    start_ms=cur_start,
                    end_ms=cur_end,
                    speaker=cur_speaker,
                )
            )
        cur_text_parts = []
        cur_start = None
        cur_end = None
        cur_speaker = None

    for line in lines:
        text = normalize_text(line.text)
        if not text:
            continue

        speaker_changed = cur_speaker is not None and line.speaker != cur_speaker
        has_large_gap = (
            cur_end is not None
            and line.start_ms is not None
            and (line.start_ms - cur_end) > 15_000
        )
        if cur_text_parts and (speaker_changed or has_large_gap):
            flush()

        if not cur_text_parts:
            cur_start = line.start_ms
            cur_speaker = line.speaker
        cur_end = line.end_ms
        cur_text_parts.append(text)

        if _SENTENCE_END_RE.search(text):
            flush()

    flush()
    return messages


def _resolve_virtual_anchor(source: Source) -> datetime | None:
    raw_meta = source.raw_meta or {}
    ts = raw_meta.get("timestamp")
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    if isinstance(ts, str) and ts.strip().isdigit():
        try:
            return datetime.fromtimestamp(float(ts.strip()), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass

    upload_date = raw_meta.get("upload_date")
    if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    if source.published_at:
        published = source.published_at
        if published.tzinfo is None:
            return published.replace(tzinfo=timezone.utc)
        return published.astimezone(timezone.utc)
    return None


def _virtual_time(anchor: datetime | None, offset_ms: int | None) -> str | None:
    if anchor is None or offset_ms is None:
        return None
    value = anchor + timedelta(milliseconds=max(0, offset_ms))
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def chunk_transcript(source: Source, lines: list[TranscriptLine], *, cfg: ChunkingConfig | None = None) -> list[Segment]:
    cfg = cfg or ChunkingConfig(target_chars=1000, max_chars=1200)
    normalized_lines: list[TranscriptLine] = []
    for line in lines:
        text = normalize_text(line.text)
        if not text:
            continue
        normalized_lines.append(
            TranscriptLine(
                text=text,
                start_ms=line.start_ms,
                end_ms=line.end_ms,
                speaker=line.speaker,
            )
        )

    messages = _merge_transcript_messages(normalized_lines, cfg)
    anchor = _resolve_virtual_anchor(source)
    segments: list[Segment] = []
    for message in messages:
        rendered = f"{message.speaker}: {message.text}" if message.speaker else message.text
        for piece in [rendered]:
            piece = piece.strip()
            if not piece:
                continue
            segments.append(
                build_segment(
                    source=source,
                    seq=len(segments),
                    text=piece,
                    sha256=sha256_text(piece),
                    start_ms=message.start_ms,
                    end_ms=message.end_ms,
                    speaker=message.speaker,
                    virtual_start_at=_virtual_time(anchor, message.start_ms),
                    virtual_end_at=_virtual_time(anchor, message.end_ms),
                )
            )
    return segments
