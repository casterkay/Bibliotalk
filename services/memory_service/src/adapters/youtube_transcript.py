from __future__ import annotations

import asyncio
import html
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..domain.errors import (
    AccessRestrictedError,
    AdapterError,
    RetryLaterError,
    UnsupportedSourceError,
)
from ..domain.models import Source, SourceContent, TranscriptContent, TranscriptLine


@dataclass(frozen=True, slots=True)
class YouTubeVideoMetadata:
    title: str | None
    channel_name: str | None
    channel_id: str | None
    published_at: datetime | None
    duration_s: int | None
    webpage_url: str | None
    raw_meta: dict[str, Any]


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptFetch:
    provider: str
    lines: list[TranscriptLine]
    language: str | None
    is_auto_captions: bool | None
    provider_meta: dict[str, Any]
    video_metadata: YouTubeVideoMetadata | None = None


class YouTubeTranscriptProvider(Protocol):
    name: str

    def fetch(
        self, video_id: str, *, preferred_languages: Sequence[str] | None
    ) -> YouTubeTranscriptFetch: ...


def _collapse_ws(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip()


_MEMBERS_ONLY_MARKERS = (
    "members-only",
    "join this channel to get access",
    "get access to members-only content",
)


def _is_members_only_error_message(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _MEMBERS_ONLY_MARKERS)


def _apply_yt_dlp_impersonate(ydl_opts: dict[str, Any], target: str | None) -> None:
    cleaned = (target or "").strip()
    if not cleaned:
        return
    try:
        from yt_dlp.networking.impersonate import (  # type: ignore[import-not-found]
            ImpersonateTarget,
        )
    except Exception:
        return
    try:
        ydl_opts["impersonate"] = ImpersonateTarget(cleaned)
    except Exception:
        ydl_opts["impersonate"] = cleaned


def _extract_yt_dlp_http_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


_VTT_TIME_RE = re.compile(
    r"^(?P<a>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<b>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _parse_vtt_timestamp(value: str) -> int:
    # WebVTT uses either HH:MM:SS.mmm or MM:SS.mmm
    parts = value.split(":")
    if len(parts) == 2:
        minutes, rest = parts
        hours = 0
    elif len(parts) == 3:
        hours_s, minutes, rest = parts
        hours = int(hours_s)
    else:
        raise ValueError(f"invalid VTT timestamp: {value!r}")

    seconds_s, ms_s = rest.split(".")
    return (hours * 3600 + int(minutes) * 60 + int(seconds_s)) * 1000 + int(ms_s)


def parse_webvtt(text: str) -> list[TranscriptLine]:
    lines: list[TranscriptLine] = []
    current_start: int | None = None
    current_end: int | None = None
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_start, current_end, current_text
        joined = _collapse_ws(" ".join(current_text))
        if current_start is not None and joined:
            cleaned = html.unescape(_VTT_TAG_RE.sub("", joined))
            lines.append(TranscriptLine(text=cleaned, start_ms=current_start, end_ms=current_end))
        current_start = None
        current_end = None
        current_text = []

    for raw in text.splitlines():
        line = raw.strip("\ufeff").rstrip()
        if not line:
            flush()
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE"):
            continue
        if "-->" in line:
            match = _VTT_TIME_RE.match(line)
            if not match:
                continue
            flush()
            current_start = _parse_vtt_timestamp(match.group("a"))
            current_end = _parse_vtt_timestamp(match.group("b"))
            continue
        if current_start is None:
            continue
        current_text.append(line)

    flush()
    return lines


_TTML_TIME_RE = re.compile(
    r"^(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:\.(?P<ms>\d{1,3}))?$"
)


def _parse_ttml_time(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.endswith("s"):
        try:
            return int(float(raw[:-1]) * 1000)
        except ValueError:
            return None
    match = _TTML_TIME_RE.match(raw)
    if not match:
        return None
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    ms = match.group("ms") or "0"
    ms = int(ms.ljust(3, "0")[:3])
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + ms


def parse_ttml(text: str) -> list[TranscriptLine]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("invalid TTML XML") from exc

    lines: list[TranscriptLine] = []
    for elem in root.iter():
        if not str(elem.tag).endswith("p"):
            continue
        cue_text = _collapse_ws("".join(elem.itertext()))
        if not cue_text:
            continue
        cue_text = html.unescape(cue_text)
        begin_ms = _parse_ttml_time(elem.attrib.get("begin", ""))
        end_ms = _parse_ttml_time(elem.attrib.get("end", ""))
        lines.append(TranscriptLine(text=cue_text, start_ms=begin_ms, end_ms=end_ms))
    return lines


def parse_json3(text: str) -> list[TranscriptLine]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json3") from exc

    lines: list[TranscriptLine] = []
    for event in payload.get("events", []) or []:
        segs = event.get("segs") or []
        cue_text = _collapse_ws("".join(str(seg.get("utf8") or "") for seg in segs))
        if not cue_text:
            continue
        start_ms = event.get("tStartMs")
        dur_ms = event.get("dDurationMs")
        end_ms = (
            (int(start_ms) + int(dur_ms)) if start_ms is not None and dur_ms is not None else None
        )
        lines.append(
            TranscriptLine(
                text=html.unescape(cue_text),
                start_ms=(int(start_ms) if start_ms is not None else None),
                end_ms=end_ms,
            )
        )
    return lines


def _parse_published_at_from_yt_dlp(info: dict[str, Any]) -> datetime | None:
    timestamp = info.get("timestamp")
    if isinstance(timestamp, (int, float)):
        try:
            return datetime.fromtimestamp(float(timestamp), tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None

    upload_date = info.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            return None

    return None


def _normalize_lang(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _lang_prefix(value: str) -> str:
    return _normalize_lang(value).split("-", 1)[0]


def _preferred_langs(preferred: Sequence[str] | None) -> list[str]:
    if not preferred:
        return []
    out: list[str] = []
    for item in preferred:
        cleaned = item.strip()
        if not cleaned:
            continue
        out.append(cleaned)
    return out


@dataclass(frozen=True, slots=True)
class _CaptionSelection:
    language: str
    is_auto: bool
    ext: str
    url: str


def _select_caption(
    *,
    subtitles: dict[str, list[dict[str, Any]]] | None,
    automatic_captions: dict[str, list[dict[str, Any]]] | None,
    preferred_languages: Sequence[str] | None,
    allow_auto: bool,
) -> _CaptionSelection | None:
    subtitle_map = subtitles or {}
    auto_map = automatic_captions or {}

    preferred = _preferred_langs(preferred_languages)
    preferred_norm = [_normalize_lang(x) for x in preferred]
    preferred_prefix = {_lang_prefix(x) for x in preferred}

    def build_key_map(keys: Sequence[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in keys:
            out[_normalize_lang(key)] = key
        return out

    def pick_lang(available_keys: list[str]) -> list[str]:
        if not available_keys:
            return []
        key_map = build_key_map(available_keys)

        ordered: list[str] = []
        for want in preferred_norm:
            if want.endswith(".*") or want.endswith("*"):
                prefix = want.removesuffix(".*").removesuffix("*")
                ordered.extend([key for norm, key in key_map.items() if norm.startswith(prefix)])
                continue
            if want in key_map:
                ordered.append(key_map[want])

        if preferred_prefix:
            ordered.extend(
                [
                    key
                    for norm, key in key_map.items()
                    if _lang_prefix(norm) in preferred_prefix and key not in ordered
                ]
            )

        ordered.extend([k for k in available_keys if k not in ordered])
        return ordered

    def pick_track(tracks: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not tracks:
            return None
        by_ext: dict[str, dict[str, Any]] = {}
        for t in tracks:
            ext = str(t.get("ext") or "").lower()
            if ext and "url" in t:
                by_ext.setdefault(ext, t)
        for ext in ("vtt", "ttml", "json3", "srv3", "srv2", "srv1"):
            if ext in by_ext:
                return by_ext[ext]
        return tracks[0] if "url" in tracks[0] else None

    for lang in pick_lang(list(subtitle_map.keys())):
        track = pick_track(subtitle_map.get(lang) or [])
        if track and track.get("url"):
            ext = str(track.get("ext") or "").lower() or "unknown"
            return _CaptionSelection(language=lang, is_auto=False, ext=ext, url=str(track["url"]))

    if not allow_auto:
        return None

    for lang in pick_lang(list(auto_map.keys())):
        track = pick_track(auto_map.get(lang) or [])
        if track and track.get("url"):
            ext = str(track.get("ext") or "").lower() or "unknown"
            return _CaptionSelection(language=lang, is_auto=True, ext=ext, url=str(track["url"]))

    return None


class YouTubeTranscriptApiProvider:
    name = "youtube_transcript_api"

    def fetch(
        self, video_id: str, *, preferred_languages: Sequence[str] | None
    ) -> YouTubeTranscriptFetch:
        try:
            from youtube_transcript_api import (
                YouTubeTranscriptApi,  # type: ignore[import-not-found]
            )
        except ModuleNotFoundError as exc:
            raise UnsupportedSourceError(
                "youtube-transcript-api is not installed. Install with `pip install 'memory_service[ingest]'`."
            ) from exc

        try:
            transcript: list[dict[str, Any]]
            if hasattr(YouTubeTranscriptApi, "get_transcript"):
                try:
                    transcript = YouTubeTranscriptApi.get_transcript(
                        video_id,
                        languages=list(_preferred_langs(preferred_languages)) or None,
                    )  # type: ignore[attr-defined]
                except TypeError:
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
        except Exception as exc:
            if _is_members_only_error_message(str(exc)):
                raise AccessRestrictedError(
                    f"YouTube transcript is members-only for video_id={video_id}"
                ) from exc
            raise AdapterError(
                f"YouTubeTranscriptApi failed for video_id={video_id}: {exc}"
            ) from exc

        lines: list[TranscriptLine] = []
        for item in transcript:
            text = _collapse_ws(str(item.get("text", "")))
            if not text:
                continue
            start_s = float(item.get("start", 0.0))
            dur_s = float(item.get("duration", 0.0))
            start_ms = int(start_s * 1000)
            end_ms = int((start_s + dur_s) * 1000) if dur_s else None
            lines.append(TranscriptLine(text=text, start_ms=start_ms, end_ms=end_ms))

        return YouTubeTranscriptFetch(
            provider=self.name,
            lines=lines,
            language=None,
            is_auto_captions=None,
            provider_meta={"transcript_line_count": len(lines)},
        )


class YtDlpCaptionsProvider:
    name = "yt_dlp"

    def __init__(
        self,
        *,
        timeout_s: float = 20.0,
        allow_auto_captions: bool = True,
        cookiefile: str | None = None,
        impersonate_target: str | None = "chrome",
    ) -> None:
        self._timeout_s = float(timeout_s)
        self._allow_auto = bool(allow_auto_captions)
        self._cookiefile = cookiefile
        self._impersonate_target = impersonate_target

    def fetch(
        self, video_id: str, *, preferred_languages: Sequence[str] | None
    ) -> YouTubeTranscriptFetch:
        try:
            from yt_dlp import YoutubeDL  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise UnsupportedSourceError(
                "yt-dlp is not installed. Install with `pip install 'memory_service'`."
            ) from exc

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts: dict[str, Any] = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": self._timeout_s,
        }
        if self._cookiefile:
            ydl_opts["cookiefile"] = self._cookiefile
        _apply_yt_dlp_impersonate(ydl_opts, self._impersonate_target)

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                selection = _select_caption(
                    subtitles=info.get("subtitles"),
                    automatic_captions=info.get("automatic_captions"),
                    preferred_languages=preferred_languages,
                    allow_auto=self._allow_auto,
                )
                if selection is None:
                    raise AdapterError(f"yt-dlp found no captions for video_id={video_id}")

                try:
                    with ydl.urlopen(selection.url) as resp:
                        caption_text = resp.read().decode("utf-8", errors="replace")
                except Exception as exc:
                    status = _extract_yt_dlp_http_status(exc)
                    if status == 429:
                        raise RetryLaterError(
                            f"rate limited downloading captions for video_id={video_id}: {exc}"
                        ) from exc
                    raise AdapterError(
                        f"failed to download captions for video_id={video_id}: {exc}"
                    ) from exc
        except (AccessRestrictedError, RetryLaterError):
            raise
        except Exception as exc:
            if _is_members_only_error_message(str(exc)):
                raise AccessRestrictedError(
                    f"YouTube video is members-only for video_id={video_id}"
                ) from exc
            raise AdapterError(
                f"yt-dlp metadata extraction failed for video_id={video_id}: {exc}"
            ) from exc

        ext = selection.ext.lower()
        try:
            if ext == "vtt":
                lines = parse_webvtt(caption_text)
            elif ext == "ttml":
                lines = parse_ttml(caption_text)
            elif ext == "json3":
                lines = parse_json3(caption_text)
            else:
                raise AdapterError(f"unsupported caption format ext={selection.ext!r}")
        except Exception as exc:
            raise AdapterError(
                f"failed to parse captions video_id={video_id} ext={selection.ext}: {exc}"
            ) from exc

        video_meta = YouTubeVideoMetadata(
            title=(str(info.get("title")) if info.get("title") else None),
            channel_name=(str(info.get("channel")) if info.get("channel") else None),
            channel_id=(str(info.get("channel_id")) if info.get("channel_id") else None),
            published_at=_parse_published_at_from_yt_dlp(info),
            duration_s=(
                int(info.get("duration"))
                if isinstance(info.get("duration"), (int, float))
                else None
            ),
            webpage_url=(str(info.get("webpage_url")) if info.get("webpage_url") else None),
            raw_meta={
                "title": info.get("title"),
                "channel": info.get("channel"),
                "channel_id": info.get("channel_id"),
                "upload_date": info.get("upload_date"),
                "timestamp": info.get("timestamp"),
                "duration_s": info.get("duration"),
                "webpage_url": info.get("webpage_url"),
            },
        )

        return YouTubeTranscriptFetch(
            provider=self.name,
            lines=lines,
            language=selection.language,
            is_auto_captions=selection.is_auto,
            provider_meta={
                "caption_language": selection.language,
                "caption_is_auto": selection.is_auto,
                "caption_ext": selection.ext,
                "transcript_line_count": len(lines),
            },
            video_metadata=video_meta,
        )


class YtDlpMetadataFetcher:
    def __init__(
        self,
        *,
        cookiefile: str | None = None,
        impersonate_target: str | None = "chrome",
    ) -> None:
        self._cookiefile = cookiefile
        self._impersonate_target = impersonate_target

    def fetch(self, video_id: str) -> YouTubeVideoMetadata:
        try:
            from yt_dlp import YoutubeDL  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise UnsupportedSourceError(
                "yt-dlp is not installed. Install with `pip install 'memory_service'`."
            ) from exc

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts: dict[str, Any] = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        if self._cookiefile:
            ydl_opts["cookiefile"] = self._cookiefile
        _apply_yt_dlp_impersonate(ydl_opts, self._impersonate_target)

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return YouTubeVideoMetadata(
            title=(str(info.get("title")) if info.get("title") else None),
            channel_name=(str(info.get("channel")) if info.get("channel") else None),
            channel_id=(str(info.get("channel_id")) if info.get("channel_id") else None),
            published_at=_parse_published_at_from_yt_dlp(info),
            duration_s=(
                int(info.get("duration"))
                if isinstance(info.get("duration"), (int, float))
                else None
            ),
            webpage_url=(str(info.get("webpage_url")) if info.get("webpage_url") else None),
            raw_meta={
                "title": info.get("title"),
                "channel": info.get("channel"),
                "channel_id": info.get("channel_id"),
                "upload_date": info.get("upload_date"),
                "timestamp": info.get("timestamp"),
                "duration_s": info.get("duration"),
                "webpage_url": info.get("webpage_url"),
            },
        )


class YouTubeTranscriptService:
    def __init__(
        self,
        *,
        providers: Sequence[YouTubeTranscriptProvider],
        preferred_languages: Sequence[str] | None = None,
        allow_auto_captions: bool = True,
        yt_dlp_cookiefile: str | None = None,
        yt_dlp_impersonate_target: str | None = "chrome",
    ) -> None:
        if not providers:
            raise ValueError("providers must be non-empty")
        self._providers = list(providers)
        self._preferred_languages = list(_preferred_langs(preferred_languages)) or None
        self._allow_auto_captions = bool(allow_auto_captions)
        self._metadata_fetcher = YtDlpMetadataFetcher(
            cookiefile=yt_dlp_cookiefile,
            impersonate_target=yt_dlp_impersonate_target,
        )

    @staticmethod
    def build_default(
        *,
        provider_order: Sequence[str] = ("yt_dlp", "youtube_transcript_api"),
        preferred_languages: Sequence[str] | None = None,
        allow_auto_captions: bool = True,
        yt_dlp_cookiefile: str | None = None,
        yt_dlp_impersonate_target: str | None = "chrome",
        timeout_s: float = 20.0,
    ) -> YouTubeTranscriptService:
        providers: list[YouTubeTranscriptProvider] = []
        for name in provider_order:
            key = name.strip().lower()
            if not key:
                continue
            if key in {"yt_dlp", "ytdlp", "yt-dlp"}:
                providers.append(
                    YtDlpCaptionsProvider(
                        timeout_s=timeout_s,
                        allow_auto_captions=allow_auto_captions,
                        cookiefile=yt_dlp_cookiefile,
                        impersonate_target=yt_dlp_impersonate_target,
                    )
                )
            elif key in {"youtube_transcript_api", "youtube-transcript-api", "yta"}:
                providers.append(YouTubeTranscriptApiProvider())
            else:
                raise ValueError(f"unknown YouTube transcript provider: {name!r}")
        return YouTubeTranscriptService(
            providers=providers,
            preferred_languages=preferred_languages,
            allow_auto_captions=allow_auto_captions,
            yt_dlp_cookiefile=yt_dlp_cookiefile,
            yt_dlp_impersonate_target=yt_dlp_impersonate_target,
        )

    async def fetch(self, video_id: str) -> YouTubeTranscriptFetch:
        errors: list[str] = []
        last_exc: Exception | None = None

        for provider in self._providers:
            try:
                fetch = await asyncio.to_thread(
                    provider.fetch, video_id, preferred_languages=self._preferred_languages
                )
            except AccessRestrictedError:
                raise
            except Exception as exc:
                last_exc = exc
                errors.append(f"{provider.name}: {exc}")
                continue

            if fetch.video_metadata is not None:
                return fetch

            try:
                meta = await asyncio.to_thread(self._metadata_fetcher.fetch, video_id)
            except Exception as exc:
                meta = YouTubeVideoMetadata(
                    title=None,
                    channel_name=None,
                    channel_id=None,
                    published_at=None,
                    duration_s=None,
                    webpage_url=None,
                    raw_meta={"metadata_fetch_error": str(exc)},
                )

            return YouTubeTranscriptFetch(
                provider=fetch.provider,
                lines=fetch.lines,
                language=fetch.language,
                is_auto_captions=fetch.is_auto_captions,
                provider_meta={**fetch.provider_meta, "metadata_provider": "yt_dlp"},
                video_metadata=meta,
            )

        detail = "; ".join(errors) if errors else "no providers configured"
        if _is_members_only_error_message(detail):
            raise AccessRestrictedError(
                f"YouTube transcript is members-only for video_id={video_id}"
            ) from last_exc
        if "429 too many requests" in detail.lower():
            raise RetryLaterError(
                f"YouTube transcript fetch rate limited for video_id={video_id}: {detail}"
            ) from last_exc
        raise AdapterError(
            f"Failed to fetch YouTube transcript for video_id={video_id} via providers: {detail}"
        ) from last_exc


async def load_youtube_transcript_source(
    *,
    user_id: str,
    external_id: str,
    title: str,
    video_id: str,
    source_url: str | None = None,
    transcript_service: YouTubeTranscriptService | None = None,
) -> SourceContent:
    service = transcript_service or YouTubeTranscriptService.build_default()
    fetch = await service.fetch(video_id)

    meta = fetch.video_metadata
    resolved_title = (meta.title if meta and meta.title else None) or title
    resolved_url = (
        source_url
        or (meta.webpage_url if meta and meta.webpage_url else None)
        or f"https://www.youtube.com/watch?v={video_id}"
    )

    raw_meta: dict[str, Any] = {"youtube_video_id": video_id, "transcript_provider": fetch.provider}
    if meta is not None:
        raw_meta.update(meta.raw_meta)
    raw_meta.update(fetch.provider_meta)

    source = Source(
        user_id=user_id,
        external_id=(external_id or video_id),
        title=str(resolved_title),
        source_url=str(resolved_url),
        channel_name=(meta.channel_name if meta else None),
        published_at=(meta.published_at if meta else None),
        raw_meta=raw_meta,
    )
    return SourceContent(source=source, content=TranscriptContent(lines=fetch.lines))
