from __future__ import annotations

import json
import subprocess
from typing import Any

from ..domain.errors import AdapterError, UnsupportedSourceError
from ..domain.models import Source, SourceContent, TranscriptContent, TranscriptLine


def _fetch_video_metadata(video_id: str) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--dump-single-json",
        "--no-warnings",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"metadata_fetch_error": (proc.stderr.strip() or "yt-dlp failed")}

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"metadata_fetch_error": "failed to parse yt-dlp JSON metadata"}

    return {
        "video_title": payload.get("title"),
        "video_description": payload.get("description"),
        "channel": payload.get("channel"),
        "channel_id": payload.get("channel_id"),
        "uploader": payload.get("uploader"),
        "uploader_id": payload.get("uploader_id"),
        "upload_date": payload.get("upload_date"),
        "timestamp": payload.get("timestamp"),
        "duration_s": payload.get("duration"),
        "view_count": payload.get("view_count"),
        "tags": payload.get("tags"),
        "categories": payload.get("categories"),
        "webpage_url": payload.get("webpage_url"),
    }


async def load_youtube_transcript_source(
    *,
    user_id: str,
    external_id: str,
    title: str,
    video_id: str,
    canonical_url: str | None = None,
) -> SourceContent:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise UnsupportedSourceError(
            "youtube-transcript-api is not installed. Install with `pip install 'ingestion_service[ingest]'`."
        ) from exc

    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)  # type: ignore[attr-defined]
        else:
            fetched = YouTubeTranscriptApi().fetch(video_id)
            transcript = (
                fetched.to_raw_data()
                if hasattr(fetched, "to_raw_data")
                else [
                    {
                        "text": getattr(item, "text", ""),
                        "start": float(getattr(item, "start", 0.0)),
                        "duration": float(getattr(item, "duration", 0.0)),
                    }
                    for item in fetched
                ]
            )
    except Exception as exc:  # noqa: BLE001
        raise AdapterError(
            f"Failed to fetch YouTube transcript for video_id={video_id}: {exc}"
        ) from exc

    lines: list[TranscriptLine] = []
    for item in transcript:
        text = str(item.get("text", "")).replace("\n", " ").strip()
        if not text:
            continue
        start_s = float(item.get("start", 0.0))
        dur_s = float(item.get("duration", 0.0))
        start_ms = int(start_s * 1000)
        end_ms = int((start_s + dur_s) * 1000) if dur_s else None
        lines.append(TranscriptLine(text=text, start_ms=start_ms, end_ms=end_ms))

    meta = _fetch_video_metadata(video_id)
    resolved_title = str(meta.get("video_title") or title)
    source = Source(
        user_id=user_id,
        platform="youtube",
        external_id=external_id or video_id,
        title=resolved_title,
        canonical_url=canonical_url or f"https://www.youtube.com/watch?v={video_id}",
        raw_meta={
            "youtube_video_id": video_id,
            **meta,
            "transcript_line_count": len(lines),
            "conversation_strategy": "sentence_end_merge",
        },
    )
    return SourceContent(source=source, content=TranscriptContent(lines=lines))

