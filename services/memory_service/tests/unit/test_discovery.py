from __future__ import annotations

from datetime import UTC, datetime

import pytest
from memory_service.adapters.rss_feed import FeedEntry
from memory_service.domain.errors import AdapterError
from memory_service.pipeline.discovery import (
    DiscoveredVideo,
    compute_discovery_delta,
    discover_subscription,
)


def test_compute_discovery_delta_uses_last_seen_video_id() -> None:
    entries = [
        DiscoveredVideo(
            "vid-c",
            "C",
            "https://www.youtube.com/watch?v=vid-c",
            datetime(2024, 1, 3, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-b",
            "B",
            "https://www.youtube.com/watch?v=vid-b",
            datetime(2024, 1, 2, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-a",
            "A",
            "https://www.youtube.com/watch?v=vid-a",
            datetime(2024, 1, 1, tzinfo=UTC),
            None,
            {},
        ),
    ]

    delta = compute_discovery_delta(entries, last_seen_video_id="vid-a", last_published_at=None)

    assert [item.video_id for item in delta] == ["vid-b", "vid-c"]


def test_compute_discovery_delta_stops_at_last_seen_video_id() -> None:
    entries = [
        DiscoveredVideo(
            "vid-c",
            "C",
            "https://www.youtube.com/watch?v=vid-c",
            datetime(2024, 1, 3, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-b",
            "B",
            "https://www.youtube.com/watch?v=vid-b",
            datetime(2024, 1, 2, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-a",
            "A",
            "https://www.youtube.com/watch?v=vid-a",
            datetime(2024, 1, 1, tzinfo=UTC),
            None,
            {},
        ),
    ]

    delta = compute_discovery_delta(entries, last_seen_video_id="vid-b", last_published_at=None)

    assert [item.video_id for item in delta] == ["vid-c"]


def test_compute_discovery_delta_falls_back_to_published_at() -> None:
    entries = [
        DiscoveredVideo(
            "vid-c",
            "C",
            "https://www.youtube.com/watch?v=vid-c",
            datetime(2024, 1, 3, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-b",
            "B",
            "https://www.youtube.com/watch?v=vid-b",
            datetime(2024, 1, 2, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-a",
            "A",
            "https://www.youtube.com/watch?v=vid-a",
            datetime(2024, 1, 1, tzinfo=UTC),
            None,
            {},
        ),
    ]

    delta = compute_discovery_delta(
        entries,
        last_seen_video_id=None,
        last_published_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    assert [item.video_id for item in delta] == ["vid-b", "vid-c"]


def test_compute_discovery_delta_coerces_naive_last_published_at_to_utc() -> None:
    entries = [
        DiscoveredVideo(
            "vid-b",
            "B",
            "https://www.youtube.com/watch?v=vid-b",
            datetime(2024, 1, 2, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-a",
            "A",
            "https://www.youtube.com/watch?v=vid-a",
            datetime(2024, 1, 1, tzinfo=UTC),
            None,
            {},
        ),
    ]

    # SQLite commonly yields naive datetimes even when the column is declared timezone-aware.
    delta = compute_discovery_delta(
        entries, last_seen_video_id=None, last_published_at=datetime(2024, 1, 1)
    )

    assert [item.video_id for item in delta] == ["vid-b"]


def test_compute_discovery_delta_handles_unsorted_input() -> None:
    entries = [
        DiscoveredVideo(
            "vid-a",
            "A",
            "https://www.youtube.com/watch?v=vid-a",
            datetime(2024, 1, 1, tzinfo=UTC),
            None,
            {},
        ),
        DiscoveredVideo(
            "vid-b",
            "B",
            "https://www.youtube.com/watch?v=vid-b",
            datetime(2024, 1, 2, tzinfo=UTC),
            None,
            {},
        ),
    ]

    delta = compute_discovery_delta(
        entries,
        last_seen_video_id=None,
        last_published_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    assert [item.video_id for item in delta] == ["vid-b"]


@pytest.mark.anyio
async def test_discover_subscription_falls_back_to_rss() -> None:
    async def failing_yt_dlp(_: str):
        raise AdapterError("yt-dlp failed")

    async def fake_rss(_: str):
        return [
            FeedEntry(
                video_id="vid-a",
                url="https://www.youtube.com/watch?v=vid-a",
                title="Video A",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                raw_meta={"feed_url": "https://example.com/feed"},
            )
        ]

    delta = await discover_subscription(
        "https://example.com/feed",
        yt_dlp_loader=failing_yt_dlp,
        rss_loader=fake_rss,
    )

    assert len(delta) == 1
    assert delta[0].video_id == "vid-a"


@pytest.mark.anyio
async def test_discover_subscription_bootstraps_feed_url_with_yt_dlp() -> None:
    seen: list[str] = []

    async def fake_yt_dlp(url: str):
        seen.append(url)
        return {
            "entries": [
                {"id": "vid-b", "title": "B", "timestamp": 1704153600},
                {"id": "vid-a", "title": "A", "timestamp": 1704067200},
            ]
        }

    async def fake_rss(_: str):
        raise AssertionError("rss should not be used during bootstrap when yt-dlp succeeds")

    delta = await discover_subscription(
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC123",
        bootstrap=True,
        yt_dlp_loader=fake_yt_dlp,
        rss_loader=fake_rss,
    )

    assert seen == ["https://www.youtube.com/channel/UC123"]
    assert [item.video_id for item in delta] == ["vid-a", "vid-b"]


@pytest.mark.anyio
async def test_discover_subscription_handles_missing_yt_dlp_binary() -> None:
    async def missing_yt_dlp(_: str):
        raise FileNotFoundError("yt-dlp")

    async def fake_rss(_: str):
        return [
            FeedEntry(
                video_id="vid-a",
                url="https://www.youtube.com/watch?v=vid-a",
                title="Video A",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                raw_meta={"feed_url": "https://example.com/feed"},
            )
        ]

    delta = await discover_subscription(
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC123",
        yt_dlp_loader=missing_yt_dlp,
        rss_loader=fake_rss,
    )

    assert [item.video_id for item in delta] == ["vid-a"]


@pytest.mark.anyio
async def test_discover_subscription_expands_channel_tabs_from_handle_root() -> None:
    calls: list[str] = []

    async def fake_yt_dlp(url: str):
        calls.append(url)
        if url == "https://www.youtube.com/@AlanWattsOrg":
            return {
                "entries": [
                    {
                        "_type": "playlist",
                        "id": "UC3wxPA1Sph--HxKGdOGVjrg",
                        "title": "Official Alan Watts Org - Videos",
                        "webpage_url": "https://www.youtube.com/@AlanWattsOrg/videos",
                    },
                    {
                        "_type": "playlist",
                        "id": "UC3wxPA1Sph--HxKGdOGVjrg",
                        "title": "Official Alan Watts Org - Shorts",
                        "webpage_url": "https://www.youtube.com/@AlanWattsOrg/shorts",
                    },
                ]
            }
        if url.endswith("/videos"):
            return {"entries": [{"id": "vid-a", "title": "A", "timestamp": 1704067200}]}
        if url.endswith("/shorts"):
            return {"entries": [{"id": "vid-b", "title": "B", "timestamp": 1704153600}]}
        raise AssertionError(f"unexpected yt-dlp url: {url}")

    async def fake_rss(_: str):
        raise AssertionError("rss should not be used when yt-dlp succeeds")

    delta = await discover_subscription(
        "https://www.youtube.com/@AlanWattsOrg",
        yt_dlp_loader=fake_yt_dlp,
        rss_loader=fake_rss,
    )

    assert calls == [
        "https://www.youtube.com/@AlanWattsOrg",
        "https://www.youtube.com/@AlanWattsOrg/videos",
        "https://www.youtube.com/@AlanWattsOrg/shorts",
    ]
    assert [item.video_id for item in delta] == ["vid-a", "vid-b"]
