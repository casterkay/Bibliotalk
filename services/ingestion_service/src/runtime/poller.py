from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from bt_common.evermemos_client import EverMemOSClient
from bt_common.evidence_store.models import Figure, IngestState, Source, Subscription
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..adapters.youtube_transcript import YouTubeTranscriptService, load_youtube_transcript_source
from ..domain.errors import AccessRestrictedError, RetryLaterError
from ..domain.ids import build_group_id
from ..pipeline.discovery import DiscoveredVideo, discover_subscription
from ..pipeline.index import IngestionIndex
from ..pipeline.ingest import ingest_source, manual_reingest_source, upsert_source_record
from .config import RuntimeConfig


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class SubscriptionConcurrencyGate:
    def __init__(self, *, global_limit: int) -> None:
        self._global = asyncio.Semaphore(max(1, global_limit))
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def run(self, subscription_id: UUID, operation: Callable[[], Awaitable[object]]):
        async with self._global:
            lock = await self._get_lock(subscription_id)
            async with lock:
                return await operation()

    async def _get_lock(self, subscription_id: UUID) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(subscription_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[subscription_id] = lock
            return lock


@dataclass(slots=True)
class PollerSnapshot:
    active_subscriptions: int
    figure_slug: str | None
    discovered_videos: int = 0
    ingested_videos: int = 0
    failed_subscriptions: int = 0


class CollectorPoller:
    def __init__(
        self,
        *,
        config: RuntimeConfig,
        session_factory: async_sessionmaker[AsyncSession],
        logger,
        client: EverMemOSClient | None = None,
        discovery_fn: Callable[..., Awaitable[list[DiscoveredVideo]]] | None = None,
        transcript_loader: Callable[..., Awaitable[object]] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.config = config
        self.session_factory = session_factory
        self.logger = logger
        self.client = client
        self._sleep = sleep or asyncio.sleep
        self.discovery_fn = discovery_fn or discover_subscription
        if transcript_loader is not None:
            self._transcript_service = None
            self.transcript_loader = transcript_loader
        else:
            self._transcript_service = YouTubeTranscriptService.build_default(
                provider_order=self.config.youtube_transcript_providers,
                preferred_languages=self.config.youtube_transcript_langs,
                allow_auto_captions=self.config.youtube_allow_auto_captions,
                yt_dlp_cookiefile=self.config.yt_dlp_cookiefile,
                yt_dlp_impersonate_target=self.config.yt_dlp_impersonate_target,
            )
            self.transcript_loader = lambda **kwargs: load_youtube_transcript_source(
                **kwargs, transcript_service=self._transcript_service
            )
        self._stopped = asyncio.Event()
        self._subscription_gate = SubscriptionConcurrencyGate(
            global_limit=self.config.global_concurrency
        )

    async def run_once(self) -> PollerSnapshot:
        discovered_videos = 0
        ingested_videos = 0
        failed_subscriptions = 0

        async with self.session_factory() as session:
            stmt = (
                select(Subscription, Figure)
                .join(Figure, Figure.figure_id == Subscription.figure_id)
                .where(Subscription.is_active.is_(True))
            )
            if self.config.figure_slug:
                stmt = stmt.where(Figure.emos_user_id == self.config.figure_slug)
            subscription_rows = (await session.execute(stmt)).all()

        results = await asyncio.gather(
            *[
                self._subscription_gate.run(
                    subscription.subscription_id,
                    lambda subscription=subscription, figure=figure: self._process_subscription(
                        subscription=subscription,
                        figure=figure,
                    ),
                )
                for subscription, figure in subscription_rows
            ],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                failed_subscriptions += 1
                self.logger.error(
                    "collector subscription task failed: %s",
                    result,
                    exc_info=(type(result), result, result.__traceback__),
                )
                continue
            discovered_videos += result[0]
            ingested_videos += result[1]
            failed_subscriptions += result[2]

        self.logger.info(
            "collector poll tick figure_slug=%s subscriptions=%s discovered=%s ingested=%s failed=%s",
            self.config.figure_slug or "*",
            len(subscription_rows),
            discovered_videos,
            ingested_videos,
            failed_subscriptions,
        )
        return PollerSnapshot(
            active_subscriptions=len(subscription_rows),
            figure_slug=self.config.figure_slug,
            discovered_videos=discovered_videos,
            ingested_videos=ingested_videos,
            failed_subscriptions=failed_subscriptions,
        )

    async def _process_subscription(
        self,
        *,
        subscription: Subscription,
        figure: Figure,
    ) -> tuple[int, int, int]:
        if self.client is None:
            return (0, 0, 0)

        now = datetime.now(tz=UTC)
        discovered_count = 0
        ingested_count = 0

        manual_sources = await self._load_manual_reingest_sources(figure.figure_id)

        async with self.session_factory() as session:
            ingest_state = await session.get(IngestState, subscription.subscription_id)
            if ingest_state is None:
                ingest_state = IngestState(subscription_id=subscription.subscription_id)
                session.add(ingest_state)
                await session.commit()
                await session.refresh(ingest_state)

            next_retry_at = _ensure_utc(ingest_state.next_retry_at)
            last_published_at = _ensure_utc(ingest_state.last_published_at)

        # Manual re-ingests are operator-driven and should not be blocked by discovery backoff.
        for source_row in manual_sources:
            try:
                await self._sleep_youtube_request_gap()
                source_content = await self.transcript_loader(
                    user_id=figure.emos_user_id,
                    external_id=source_row.external_id,
                    title=source_row.title,
                    video_id=source_row.external_id,
                    source_url=source_row.source_url,
                )
                result = await manual_reingest_source(
                    source_content=source_content,
                    index=IngestionIndex(self.session_factory, path=self.config.index_path),
                    client=self.client,
                )
            except Exception:
                self.logger.exception(
                    "manual reingest crashed figure=%s video_id=%s",
                    figure.emos_user_id,
                    source_row.external_id,
                )
                continue

            if result.status != "done":
                self.logger.error(
                    "manual reingest failed figure=%s video_id=%s code=%s message=%s",
                    figure.emos_user_id,
                    source_row.external_id,
                    (result.error.code if result.error else None),
                    (result.error.message if result.error else None),
                )
                continue

            ingested_count += 1

        if next_retry_at and next_retry_at > now:
            async with self.session_factory() as session:
                ingest_state = await session.get(IngestState, subscription.subscription_id)
                if ingest_state is not None:
                    ingest_state.last_polled_at = now
                    await session.commit()
            return (0, ingested_count, 0)

        try:
            bootstrap = False
            last_seen_video_id: str | None
            async with self.session_factory() as session:
                ingest_state = await session.get(IngestState, subscription.subscription_id)
                if ingest_state is None:
                    last_seen_video_id = None
                    last_published_at = None
                    bootstrap = True
                else:
                    last_seen_video_id = ingest_state.last_seen_video_id
                    last_published_at = _ensure_utc(ingest_state.last_published_at)
                    bootstrap = (
                        ingest_state.last_polled_at is None
                        and ingest_state.last_seen_video_id is None
                        and ingest_state.last_published_at is None
                    )

            await self._sleep_youtube_request_gap()
            discovered = await self.discovery_fn(
                subscription.subscription_url,
                last_seen_video_id=last_seen_video_id,
                last_published_at=last_published_at,
                bootstrap=bootstrap,
            )
        except Exception:
            async with self.session_factory() as session:
                ingest_state = await session.get(IngestState, subscription.subscription_id)
                if ingest_state is None:
                    ingest_state = IngestState(subscription_id=subscription.subscription_id)
                    session.add(ingest_state)
                ingest_state.last_polled_at = now
                ingest_state.failure_count += 1
                backoff_minutes = min(
                    subscription.poll_interval_minutes
                    * (2 ** max(0, ingest_state.failure_count - 1)),
                    24 * 60,
                )
                ingest_state.next_retry_at = now + timedelta(minutes=backoff_minutes)
                await session.commit()
            raise

        discovered_count = len(discovered)
        index = IngestionIndex(self.session_factory, path=self.config.index_path)

        # Persist discovered sources immediately so we can safely advance the subscription cursor
        # even if transcripts are unavailable right now (rate limits, access restrictions, etc).
        for item in discovered:
            await self._upsert_discovered_source(
                index=index,
                subscription_id=subscription.subscription_id,
                figure_slug=figure.emos_user_id,
                item=item,
            )

        # Advance cursor based on discovery only. Individual source failures are handled per-source.
        latest = discovered[-1] if discovered else None
        async with self.session_factory() as session:
            ingest_state = await session.get(IngestState, subscription.subscription_id)
            if ingest_state is None:
                ingest_state = IngestState(subscription_id=subscription.subscription_id)
                session.add(ingest_state)
            ingest_state.last_polled_at = now
            if latest is not None:
                ingest_state.last_seen_video_id = latest.video_id
                ingest_state.last_published_at = _ensure_utc(latest.published_at)
            ingest_state.failure_count = 0
            ingest_state.next_retry_at = None
            await session.commit()

        # Process due sources for this subscription (newly discovered + retry queue).
        due_sources = await self._list_due_sources(
            subscription_id=subscription.subscription_id, now=now
        )
        for stored in due_sources:
            outcome = await self._attempt_source(
                index=index,
                subscription_id=subscription.subscription_id,
                figure_slug=figure.emos_user_id,
                source_row=stored,
            )
            if outcome == "ingested":
                ingested_count += 1

        return (discovered_count, ingested_count, 0)

    async def _sleep_youtube_request_gap(self) -> None:
        delay = float(getattr(self.config, "youtube_request_delay_s", 0.0) or 0.0)
        jitter = float(getattr(self.config, "youtube_request_jitter_s", 0.0) or 0.0)
        total = max(0.0, delay) + (random.random() * max(0.0, jitter))
        if total <= 0.0:
            return
        await self._sleep(total)

    async def _upsert_discovered_source(
        self,
        *,
        index: IngestionIndex,
        subscription_id: UUID,
        figure_slug: str,
        item: DiscoveredVideo,
    ) -> None:
        raw_meta: dict[str, Any] | None = item.raw_meta or None
        try:
            raw_meta_json = json.dumps(raw_meta, ensure_ascii=False) if raw_meta else None
            safe_raw_meta = raw_meta
        except TypeError:
            raw_meta_json = json.dumps(
                {"raw_meta_error": "non_json_serializable"}, ensure_ascii=False
            )
            safe_raw_meta = {"raw_meta_error": "non_json_serializable"}

        class _SourceInput:
            platform = "youtube"

            def __init__(self) -> None:
                self.user_id = figure_slug
                self.external_id = item.video_id
                self.group_id = build_group_id(
                    user_id=figure_slug, platform="youtube", external_id=item.video_id
                )
                self.title = item.title or item.video_id
                self.source_url = (
                    item.source_url or f"https://www.youtube.com/watch?v={item.video_id}"
                )
                self.channel_name = item.channel_name
                self.published_at = _ensure_utc(item.published_at)
                self.raw_meta = safe_raw_meta
                self.subscription_id = subscription_id

        # `upsert_source_record` handles unknown figures and cursor-safe updates.
        stored = await upsert_source_record(index=index, source=_SourceInput())

        # Ensure raw meta from discovery is persisted even when transcript fetch is delayed.
        async with self.session_factory() as session:
            refreshed = await session.get(Source, stored.source_id)
            if refreshed is None:
                return
            refreshed.raw_meta_json = raw_meta_json or refreshed.raw_meta_json
            if refreshed.subscription_id is None:
                refreshed.subscription_id = subscription_id
            await session.commit()

    async def _list_due_sources(self, *, subscription_id: UUID, now: datetime) -> list[Source]:
        async with self.session_factory() as session:
            stmt = (
                select(Source)
                .where(
                    Source.subscription_id == subscription_id,
                    Source.transcript_status == "pending",
                    or_(
                        Source.transcript_next_retry_at.is_(None),
                        Source.transcript_next_retry_at <= now,
                    ),
                )
                .order_by(Source.published_at, Source.source_id)
            )
            return list((await session.execute(stmt)).scalars().all())

    def _compute_retry_delay_s(self, *, attempt: int) -> int:
        # Full-jitter exponential backoff (no sleeps here; we schedule next_retry_at).
        base_s = 60
        cap_s = 24 * 60 * 60
        delay = min(cap_s, base_s * (2 ** max(0, attempt - 1)))
        jittered = int(delay * (0.5 + random.random()))
        return max(1, min(cap_s, jittered))

    async def _schedule_source_retry(
        self,
        *,
        source_id: UUID,
        now: datetime,
        reason: str,
        max_attempts: int = 8,
    ) -> None:
        retry_in_s: int | None = None
        attempt: int | None = None
        external_id: str | None = None
        async with self.session_factory() as session:
            stored = await session.get(Source, source_id)
            if stored is None:
                return
            stored.transcript_failure_count += 1
            stored.transcript_last_attempt_at = now
            stored.transcript_skip_reason = None
            external_id = stored.external_id
            if stored.transcript_failure_count >= max_attempts:
                stored.transcript_status = "failed"
                stored.transcript_next_retry_at = None
            else:
                delay_s = self._compute_retry_delay_s(attempt=stored.transcript_failure_count)
                stored.transcript_next_retry_at = now + timedelta(seconds=delay_s)
                stored.transcript_status = "pending"
                retry_in_s = delay_s
            attempt = stored.transcript_failure_count
            await session.commit()

        self.logger.warning(
            "collector source scheduled retry video_id=%s retry_in_s=%s attempt=%s reason=%s",
            external_id or str(source_id),
            retry_in_s,
            attempt,
            reason,
        )

    async def _mark_source_skipped(
        self,
        *,
        source_id: UUID,
        now: datetime,
        reason: str,
    ) -> None:
        async with self.session_factory() as session:
            stored = await session.get(Source, source_id)
            if stored is None:
                return
            stored.transcript_status = "skipped"
            stored.transcript_skip_reason = reason
            stored.transcript_failure_count = 0
            stored.transcript_last_attempt_at = now
            stored.transcript_next_retry_at = None
            await session.commit()

    async def _attempt_source(
        self,
        *,
        index: IngestionIndex,
        subscription_id: UUID,
        figure_slug: str,
        source_row: Source,
    ) -> str:
        del subscription_id
        now = datetime.now(tz=UTC)

        if source_row.transcript_status != "pending":
            return "skipped"
        next_retry_at = _ensure_utc(source_row.transcript_next_retry_at)
        if next_retry_at and next_retry_at > now:
            return "skipped"

        async with self.session_factory() as session:
            stored = await session.get(Source, source_row.source_id)
            if stored is None:
                return "skipped"
            stored.transcript_last_attempt_at = now
            await session.commit()

        try:
            await self._sleep_youtube_request_gap()
            source_content = await self.transcript_loader(
                user_id=figure_slug,
                external_id=source_row.external_id,
                title=source_row.title,
                video_id=source_row.external_id,
                source_url=source_row.source_url,
            )
        except AccessRestrictedError:
            await self._mark_source_skipped(
                source_id=source_row.source_id, now=now, reason="members_only"
            )
            self.logger.info(
                "collector skipped members-only video figure=%s video_id=%s",
                figure_slug,
                source_row.external_id,
            )
            return "skipped"
        except RetryLaterError as exc:
            await self._schedule_source_retry(
                source_id=source_row.source_id, now=now, reason=str(exc)
            )
            return "retry"
        except Exception as exc:
            await self._schedule_source_retry(
                source_id=source_row.source_id, now=now, reason=f"transcript_error:{exc}"
            )
            return "retry"

        result = await ingest_source(
            source_content=source_content,
            index=index,
            client=self.client,
        )
        if result.status == "done":
            return "ingested"

        await self._schedule_source_retry(
            source_id=source_row.source_id, now=now, reason="ingest_failed"
        )
        return "retry"

    async def _load_manual_reingest_sources(self, figure_id) -> list[Source]:
        async with self.session_factory() as session:
            stmt = (
                select(Source)
                .where(
                    Source.figure_id == figure_id,
                    Source.manual_ingestion_requested_at.is_not(None),
                )
                .order_by(Source.manual_ingestion_requested_at.asc())
            )
            return list((await session.execute(stmt)).scalars().all())

    async def run_forever(self) -> None:
        while not self._stopped.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self.config.poll_interval_minutes * 60,
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()
