from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable, Protocol

from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceIngestionState, SourceTextBatch
from bt_store.models_runtime import PlatformPost
from discord_service.bot.message_models import FeedBatchMessage, FeedParentMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("discord_service")


class DiscordPublicationError(RuntimeError):
    """Base class for Discord publication failures."""


class DiscordRateLimitError(DiscordPublicationError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Discord rate limit hit; retry after {retry_after} seconds")
        self.retry_after = retry_after


class DiscordTransientError(DiscordPublicationError):
    """Retryable server-side failure."""


class DiscordPermissionError(DiscordPublicationError):
    """Non-retryable permission failure."""


class DiscordFeedTransport(Protocol):
    async def post_parent_message(self, *, channel_id: str, text: str) -> str: ...

    async def create_thread(
        self,
        *,
        channel_id: str,
        parent_message_id: str,
        name: str,
    ) -> str: ...

    async def post_thread_message(self, *, thread_id: str, text: str) -> str: ...


@dataclass(frozen=True, slots=True)
class PublishResult:
    source_id: uuid.UUID
    status: str
    parent_posted: bool = False
    thread_created: bool = False
    batches_posted: int = 0


@dataclass(frozen=True, slots=True)
class PublishSummary:
    attempted_sources: int = 0
    published_sources: int = 0
    failed_sources: int = 0


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _build_parent_text(source: Source) -> str:
    title = source.title.strip()
    url = (source.external_url or "").strip()
    content = f"{title}\n{url}"
    if len(content) <= 2000:
        return content

    title_limit = max(1, 2000 - len(url) - 4)
    clipped_title = title[:title_limit].rstrip()
    return f"{clipped_title}...\n{url}"


def _build_thread_name(source: Source) -> str:
    candidate = source.title.strip() or source.external_id
    return candidate[:100] or source.external_id[:100]


def _format_seq_label(start_ms: int | None) -> str:
    total_seconds = max((start_ms or 0) // 1000, 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"


async def _get_parent_post(
    session: AsyncSession, *, source_id: uuid.UUID
) -> PlatformPost | None:
    return (
        await session.execute(
            select(PlatformPost).where(
                PlatformPost.platform == "discord",
                PlatformPost.kind == "feed.parent",
                PlatformPost.source_id == source_id,
                PlatformPost.batch_id.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _get_or_create_parent_post(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    source_id: uuid.UUID,
    channel_id: str,
) -> PlatformPost:
    parent_post = await _get_parent_post(session, source_id=source_id)
    if parent_post is not None:
        return parent_post

    parent_post = PlatformPost(
        platform="discord",
        kind="feed.parent",
        agent_id=agent_id,
        container_id=channel_id,
        source_id=source_id,
        batch_id=None,
        segment_id=None,
        idempotency_key=f"discord:feed:source:{source_id}:parent",
        status="pending",
        error=None,
        meta_json=None,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(parent_post)
    await session.flush()
    return parent_post


async def _get_or_create_batch_post(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    source_id: uuid.UUID,
    batch: SourceTextBatch,
    channel_id: str,
) -> PlatformPost:
    text_fingerprint = hashlib.sha256((batch.text or "").encode("utf-8")).hexdigest()[
        :16
    ]
    idempotency_key = f"discord:feed:source:{source_id}:batch:{batch.start_seq}:{batch.end_seq}:{text_fingerprint}"
    post = (
        await session.execute(
            select(PlatformPost).where(
                PlatformPost.platform == "discord",
                PlatformPost.kind == "feed.batch",
                PlatformPost.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if post is not None:
        return post

    post = PlatformPost(
        platform="discord",
        kind="feed.batch",
        agent_id=agent_id,
        container_id=channel_id,
        source_id=source_id,
        batch_id=batch.batch_id,
        segment_id=None,
        idempotency_key=idempotency_key,
        status="pending",
        error=None,
        meta_json=None,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(post)
    await session.flush()
    return post


async def _publish_with_retry(
    action: Callable[[], Awaitable[str]],
    *,
    sleep: Callable[[float], Awaitable[None]],
    logger_: logging.Logger,
    source_id: uuid.UUID,
    batch_id: uuid.UUID,
    max_retries: int = 3,
) -> str:
    transient_attempts = 0
    while True:
        try:
            return await action()
        except DiscordRateLimitError as exc:
            logger_.warning(
                "discord batch post rate-limited source_id=%s batch_id=%s retry_after=%s",
                source_id,
                batch_id,
                exc.retry_after,
            )
            await sleep(max(exc.retry_after, 0.0))
        except DiscordTransientError:
            transient_attempts += 1
            if transient_attempts > max_retries:
                raise
            delay = float(2**transient_attempts)
            logger_.warning(
                "discord batch post transient failure source_id=%s batch_id=%s retry_in=%s attempt=%s",
                source_id,
                batch_id,
                delay,
                transient_attempts,
            )
            await sleep(delay)


class FeedPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        transport: DiscordFeedTransport,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._transport = transport
        self._sleep = sleep
        self._logger = logger_ or logger

    async def list_pending_source_ids(self, *, agent_id: uuid.UUID) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            sources = (
                (
                    await session.execute(
                        select(Source)
                        .join(
                            SourceIngestionState,
                            SourceIngestionState.source_id == Source.source_id,
                        )
                        .where(
                            Source.agent_id == agent_id,
                            SourceIngestionState.ingest_status == "ingested",
                        )
                        .order_by(Source.published_at, Source.source_id)
                    )
                )
                .scalars()
                .all()
            )

            pending_source_ids: list[uuid.UUID] = []
            for source in sources:
                if await self._source_has_pending_posts(
                    session, source_id=source.source_id
                ):
                    pending_source_ids.append(source.source_id)
            return pending_source_ids

    async def publish_pending_sources(
        self,
        *,
        agent_id: uuid.UUID,
        channel_id: str,
    ) -> PublishSummary:
        source_ids = await self.list_pending_source_ids(agent_id=agent_id)
        published = 0
        failed = 0
        for source_id in source_ids:
            result = await self.publish_source(
                source_id=source_id, channel_id=channel_id
            )
            if result.status == "done":
                published += 1
            else:
                failed += 1
        return PublishSummary(
            attempted_sources=len(source_ids),
            published_sources=published,
            failed_sources=failed,
        )

    async def publish_source(
        self,
        *,
        source_id: uuid.UUID,
        channel_id: str,
    ) -> PublishResult:
        async with self._session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:
                raise LookupError(f"Unknown source: {source_id}")

            ordered_batches = (
                (
                    await session.execute(
                        select(SourceTextBatch)
                        .where(SourceTextBatch.source_id == source.source_id)
                        .order_by(SourceTextBatch.start_seq, SourceTextBatch.batch_id)
                    )
                )
                .scalars()
                .all()
            )
            if not ordered_batches:
                return PublishResult(source_id=source_id, status="done")

            parent_post = await _get_or_create_parent_post(
                session,
                agent_id=source.agent_id,
                source_id=source.source_id,
                channel_id=channel_id,
            )
            await session.commit()

            parent_posted = False
            thread_created = False

            if not parent_post.platform_event_id:
                message = FeedParentMessage(
                    agent_id=source.agent_id,
                    source_id=source.source_id,
                    channel_id=channel_id,
                    text=_build_parent_text(source),
                )
                try:
                    parent_post.platform_event_id = (
                        await self._transport.post_parent_message(
                            channel_id=message.channel_id,
                            text=message.text,
                        )
                    )
                    parent_post.status = "posted"
                    parent_post.updated_at = _utc_now()
                    parent_posted = True
                    await session.commit()
                except DiscordPublicationError:
                    parent_post.status = "failed"
                    await session.commit()
                    return PublishResult(source_id=source_id, status="failed")

            if not parent_post.thread_id and parent_post.platform_event_id:
                try:
                    parent_post.thread_id = await self._transport.create_thread(
                        channel_id=channel_id,
                        parent_message_id=parent_post.platform_event_id,
                        name=_build_thread_name(source),
                    )
                    parent_post.status = "posted"
                    parent_post.updated_at = _utc_now()
                    thread_created = True
                    await session.commit()
                except DiscordPublicationError:
                    parent_post.status = "failed"
                    await session.commit()
                    return PublishResult(
                        source_id=source_id,
                        status="failed",
                        parent_posted=parent_posted,
                    )

            posted_count = 0
            for index, batch in enumerate(ordered_batches):
                batch_post = await _get_or_create_batch_post(
                    session,
                    agent_id=source.agent_id,
                    source_id=source.source_id,
                    batch=batch,
                    channel_id=channel_id,
                )
                batch_post.batch_id = batch.batch_id
                batch_post.thread_id = parent_post.thread_id
                batch_post.meta_json = {
                    "parent_message_id": parent_post.platform_event_id
                }
                batch_post.updated_at = _utc_now()
                if batch_post.status == "posted" and batch_post.platform_event_id:
                    continue

                message = FeedBatchMessage(
                    agent_id=source.agent_id,
                    source_id=source.source_id,
                    batch_id=batch.batch_id,
                    thread_id=parent_post.thread_id or "",
                    text=batch.text,
                    seq_label=_format_seq_label(batch.start_ms),
                )
                try:
                    posted_message_id = await _publish_with_retry(
                        lambda message=message: self._transport.post_thread_message(
                            thread_id=message.thread_id,
                            text=message.render_text(),
                        ),
                        sleep=self._sleep,
                        logger_=self._logger,
                        source_id=source.source_id,
                        batch_id=batch.batch_id,
                    )
                except DiscordPermissionError:
                    batch_post.status = "failed"
                    batch_post.error = "permission_error"
                    batch_post.updated_at = _utc_now()
                    await session.commit()
                    return PublishResult(
                        source_id=source_id,
                        status="failed",
                        parent_posted=parent_posted,
                        thread_created=thread_created,
                        batches_posted=posted_count,
                    )
                except DiscordPublicationError:
                    batch_post.status = "failed"
                    batch_post.error = "publication_error"
                    batch_post.updated_at = _utc_now()
                    await session.commit()
                    return PublishResult(
                        source_id=source_id,
                        status="failed",
                        parent_posted=parent_posted,
                        thread_created=thread_created,
                        batches_posted=posted_count,
                    )

                batch_post.platform_event_id = posted_message_id
                batch_post.status = "posted"
                batch_post.error = None
                batch_post.updated_at = _utc_now()
                posted_count += 1
                await session.commit()
                if index < len(ordered_batches) - 1:
                    await self._sleep(1.0)

            return PublishResult(
                source_id=source_id,
                status="done",
                parent_posted=parent_posted,
                thread_created=thread_created,
                batches_posted=posted_count,
            )

    async def _source_has_pending_posts(
        self,
        session: AsyncSession,
        *,
        source_id: uuid.UUID,
    ) -> bool:
        parent_post = await _get_parent_post(session, source_id=source_id)
        if (
            parent_post is None
            or not parent_post.platform_event_id
            or not parent_post.thread_id
        ):
            return True

        batches_total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(SourceTextBatch)
                    .where(SourceTextBatch.source_id == source_id)
                )
            ).scalar_one()
            or 0
        )
        if batches_total == 0:
            return False

        batches = (
            (
                await session.execute(
                    select(SourceTextBatch).where(
                        SourceTextBatch.source_id == source_id
                    )
                )
            )
            .scalars()
            .all()
        )
        expected_keys: set[str] = set()
        for batch in batches:
            text_fingerprint = hashlib.sha256(
                (batch.text or "").encode("utf-8")
            ).hexdigest()[:16]
            expected_keys.add(
                f"discord:feed:source:{source_id}:batch:{batch.start_seq}:{batch.end_seq}:{text_fingerprint}"
            )

        posted_keys = set(
            (
                await session.execute(
                    select(PlatformPost.idempotency_key).where(
                        PlatformPost.platform == "discord",
                        PlatformPost.kind == "feed.batch",
                        PlatformPost.source_id == source_id,
                        PlatformPost.status == "posted",
                    )
                )
            )
            .scalars()
            .all()
        )
        return not expected_keys.issubset(posted_keys)
