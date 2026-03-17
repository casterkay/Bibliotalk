from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlparse

from ..adapters.rss_feed import FeedEntry, parse_feed
from ..domain.errors import AdapterError


@dataclass(frozen=True, slots=True)
class DiscoveredVideo:
    video_id: str
    title: str
    source_url: str
    published_at: datetime | None
    channel_name: str | None
    raw_meta: dict[str, Any]


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _parse_published_at(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _parse_yt_dlp_entries(payload: dict[str, Any]) -> list[DiscoveredVideo]:
    entries = payload.get("entries") or []
    videos: list[DiscoveredVideo] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        # yt-dlp sometimes returns nested "playlist" entries (e.g. channel handle -> /videos + /shorts tabs).
        # Those are not ingestible videos; treat them as expansion candidates instead.
        if str(item.get("_type") or "").lower() == "playlist":
            continue
        video_id = item.get("id")
        if not isinstance(video_id, str) or not video_id:
            continue
        title = str(item.get("title") or video_id)
        source_url = str(item.get("url") or f"https://www.youtube.com/watch?v={video_id}")
        if not source_url.startswith("http"):
            source_url = f"https://www.youtube.com/watch?v={video_id}"
        videos.append(
            DiscoveredVideo(
                video_id=video_id,
                title=title,
                source_url=source_url,
                published_at=_parse_published_at(item.get("timestamp") or item.get("upload_date")),
                channel_name=(str(item.get("channel")) if item.get("channel") else None),
                raw_meta=item,
            )
        )
    return _sort_discovered_videos(videos)


def _sort_key(item: DiscoveredVideo) -> tuple[float, str]:
    published = item.published_at.timestamp() if item.published_at is not None else 0.0
    return (published, item.video_id or item.source_url)


def _sort_discovered_videos(entries: list[DiscoveredVideo]) -> list[DiscoveredVideo]:
    return sorted(entries, key=_sort_key, reverse=True)


def is_youtube_feed_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return hostname.endswith("youtube.com") and parsed.path == "/feeds/videos.xml"


def _bootstrap_target_url(subscription_url: str) -> str:
    if not is_youtube_feed_url(subscription_url):
        return subscription_url
    query = dict(parse_qsl(urlparse(subscription_url).query, keep_blank_values=True))
    if query.get("channel_id"):
        return f"https://www.youtube.com/channel/{query['channel_id']}"
    if query.get("playlist_id"):
        return f"https://www.youtube.com/playlist?list={query['playlist_id']}"
    if query.get("user"):
        return f"https://www.youtube.com/user/{query['user']}"
    return subscription_url


def compute_discovery_delta(
    entries: list[DiscoveredVideo],
    *,
    last_seen_video_id: str | None,
    last_published_at: datetime | None,
) -> list[DiscoveredVideo]:
    last_published_at = _ensure_utc(last_published_at)
    ordered = _sort_discovered_videos(entries)
    pending: list[DiscoveredVideo] = []
    for entry in ordered:
        if last_seen_video_id and entry.video_id == last_seen_video_id:
            break
        if (
            last_published_at
            and entry.published_at is not None
            and _ensure_utc(entry.published_at) <= last_published_at
        ):
            break
        pending.append(entry)
    return sorted(pending, key=_sort_key)


async def _run_yt_dlp(subscription_url: str) -> dict[str, Any]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        subscription_url,
    ]

    def _invoke() -> dict[str, Any]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise AdapterError("yt-dlp is not installed or not on PATH") from exc
        if proc.returncode != 0:
            raise AdapterError(proc.stderr.strip() or "yt-dlp discovery failed")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError("failed to parse yt-dlp discovery output") from exc

    return await asyncio.to_thread(_invoke)


def _from_feed_entries(entries: list[FeedEntry]) -> list[DiscoveredVideo]:
    videos: list[DiscoveredVideo] = []
    for entry in entries:
        if not entry.video_id:
            continue
        videos.append(
            DiscoveredVideo(
                video_id=entry.video_id,
                title=entry.title or entry.video_id,
                source_url=entry.url,
                published_at=entry.published_at,
                channel_name=None,
                raw_meta=entry.raw_meta,
            )
        )
    return _sort_discovered_videos(videos)


async def discover_subscription(
    subscription_url: str,
    *,
    last_seen_video_id: str | None = None,
    last_published_at: datetime | None = None,
    bootstrap: bool = False,
    yt_dlp_loader: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    rss_loader: Callable[[str], Awaitable[list[FeedEntry]]] | None = None,
) -> list[DiscoveredVideo]:
    yt_dlp_loader = yt_dlp_loader or _run_yt_dlp
    rss_loader = rss_loader or parse_feed

    try:
        if bootstrap:
            payload = await yt_dlp_loader(_bootstrap_target_url(subscription_url))
            entries = _parse_yt_dlp_entries(payload)
        elif is_youtube_feed_url(subscription_url):
            entries = _from_feed_entries(await rss_loader(subscription_url))
        else:
            payload = await yt_dlp_loader(subscription_url)
            entries = _parse_yt_dlp_entries(payload)
    except (AdapterError, FileNotFoundError):
        entries = _from_feed_entries(await rss_loader(subscription_url))

    # yt-dlp can return channel "tabs" (videos/shorts) as playlist entries when invoked on
    # a channel handle root. If that happens, expand those tabs into actual video entries.
    if not entries and isinstance(locals().get("payload"), dict):
        payload_dict: dict[str, Any] = locals()["payload"]
        tab_urls: list[str] = []
        for item in payload_dict.get("entries") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("_type") or "").lower() != "playlist":
                continue
            tab_url = item.get("webpage_url") or item.get("url")
            if isinstance(tab_url, str) and tab_url.startswith("http"):
                tab_urls.append(tab_url)
        tab_urls = list(dict.fromkeys(tab_urls))
        if tab_urls:
            expanded: list[DiscoveredVideo] = []
            for tab_url in tab_urls:
                try:
                    tab_payload = await yt_dlp_loader(tab_url)
                except (AdapterError, FileNotFoundError):
                    continue
                expanded.extend(_parse_yt_dlp_entries(tab_payload))
            # Deduplicate by video_id while preserving ordering.
            seen: set[str] = set()
            deduped: list[DiscoveredVideo] = []
            for item in _sort_discovered_videos(expanded):
                if item.video_id in seen:
                    continue
                seen.add(item.video_id)
                deduped.append(item)
            entries = deduped

    return compute_discovery_delta(
        entries,
        last_seen_video_id=last_seen_video_id,
        last_published_at=last_published_at,
    )
