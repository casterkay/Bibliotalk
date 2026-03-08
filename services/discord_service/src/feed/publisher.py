from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable, Protocol

from bt_common.evidence_store.models import DiscordPost, Source, TranscriptBatch
from discord_service.bot.message_models import FeedBatchMessage, FeedParentMessage
from discord_service.feed.batcher import ensure_source_batches, format_seq_label
from sqlalchemy import select
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
    url = source.source_url.strip()
    content = f"{title}\n{url}"
    if len(content) <= 2000:
        return content

    title_limit = max(1, 2000 - len(url) - 4)
    clipped_title = title[:title_limit].rstrip()
    return f"{clipped_title}...\n{url}"


def _build_thread_name(source: Source) -> str:
    candidate = source.title.strip() or source.external_id
    return candidate[:100] or source.external_id[:100]


async def _get_parent_post(
    session: AsyncSession, *, source_id: uuid.UUID
) -> DiscordPost | None:
    return (
        await session.execute(
            select(DiscordPost).where(
                DiscordPost.source_id == source_id,
                DiscordPost.batch_id.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _get_or_create_parent_post(
    session: AsyncSession,
    *,
    figure_id: uuid.UUID,
    source_id: uuid.UUID,
) -> DiscordPost:
    parent_post = await _get_parent_post(session, source_id=source_id)
    if parent_post is not None:
        return parent_post

    parent_post = DiscordPost(
        figure_id=figure_id,
        source_id=source_id,
        batch_id=None,
        post_status="pending",
    )
    session.add(parent_post)
    await session.flush()
    return parent_post


async def _get_or_create_batch_post(
    session: AsyncSession,
    *,
    figure_id: uuid.UUID,
    source_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> DiscordPost:
    post = (
        await session.execute(
            select(DiscordPost).where(
                DiscordPost.source_id == source_id,
                DiscordPost.batch_id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if post is not None:
        return post

    post = DiscordPost(
        figure_id=figure_id,
        source_id=source_id,
        batch_id=batch_id,
        post_status="pending",
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

    async def list_pending_source_ids(self, *, figure_id: uuid.UUID) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            sources = (
                (
                    await session.execute(
                        select(Source)
                        .where(
                            Source.figure_id == figure_id,
                            Source.transcript_status == "ingested",
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
        figure_id: uuid.UUID,
        channel_id: str,
    ) -> PublishSummary:
        source_ids = await self.list_pending_source_ids(figure_id=figure_id)
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

            batches = await ensure_source_batches(session, source_id=source_id)
            await session.commit()

        async with self._session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:
                raise LookupError(f"Unknown source: {source_id}")

            if not batches:
                return PublishResult(source_id=source_id, status="done")

            parent_post = await _get_or_create_parent_post(
                session,
                figure_id=source.figure_id,
                source_id=source.source_id,
            )
            await session.commit()

            parent_posted = False
            thread_created = False

            if not parent_post.parent_message_id:
                message = FeedParentMessage(
                    figure_id=source.figure_id,
                    source_id=source.source_id,
                    channel_id=channel_id,
                    text=_build_parent_text(source),
                )
                try:
                    parent_post.parent_message_id = (
                        await self._transport.post_parent_message(
                            channel_id=message.channel_id,
                            text=message.text,
                        )
                    )
                    parent_post.post_status = "posted"
                    parent_post.posted_at = _utc_now()
                    parent_posted = True
                    await session.commit()
                except DiscordPublicationError:
                    parent_post.post_status = "failed"
                    await session.commit()
                    return PublishResult(source_id=source_id, status="failed")

            if not parent_post.thread_id and parent_post.parent_message_id:
                try:
                    parent_post.thread_id = await self._transport.create_thread(
                        channel_id=channel_id,
                        parent_message_id=parent_post.parent_message_id,
                        name=_build_thread_name(source),
                    )
                    parent_post.post_status = "posted"
                    thread_created = True
                    await session.commit()
                except DiscordPublicationError:
                    parent_post.post_status = "failed"
                    await session.commit()
                    return PublishResult(
                        source_id=source_id,
                        status="failed",
                        parent_posted=parent_posted,
                    )

            posted_count = 0
            ordered_batches = (
                (
                    await session.execute(
                        select(TranscriptBatch)
                        .where(TranscriptBatch.source_id == source.source_id)
                        .order_by(TranscriptBatch.start_seq, TranscriptBatch.batch_id)
                    )
                )
                .scalars()
                .all()
            )
            for index, batch in enumerate(ordered_batches):
                batch_post = await _get_or_create_batch_post(
                    session,
                    figure_id=source.figure_id,
                    source_id=source.source_id,
                    batch_id=batch.batch_id,
                )
                batch_post.parent_message_id = parent_post.parent_message_id
                batch_post.thread_id = parent_post.thread_id
                if batch_post.post_status == "posted":
                    continue

                message = FeedBatchMessage(
                    figure_id=source.figure_id,
                    source_id=source.source_id,
                    batch_id=batch.batch_id,
                    thread_id=parent_post.thread_id or "",
                    text=batch.text,
                    seq_label=format_seq_label(batch.start_ms),
                )
                try:
                    await _publish_with_retry(
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
                    batch_post.post_status = "failed"
                    batch_post.posted_at = None
                    await session.commit()
                    return PublishResult(
                        source_id=source_id,
                        status="failed",
                        parent_posted=parent_posted,
                        thread_created=thread_created,
                        batches_posted=posted_count,
                    )
                except DiscordPublicationError:
                    batch_post.post_status = "failed"
                    batch_post.posted_at = None
                    await session.commit()
                    return PublishResult(
                        source_id=source_id,
                        status="failed",
                        parent_posted=parent_posted,
                        thread_created=thread_created,
                        batches_posted=posted_count,
                    )

                batch_post.post_status = "posted"
                batch_post.posted_at = _utc_now()
                batch.posted_to_discord = True
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
            or not parent_post.parent_message_id
            or not parent_post.thread_id
        ):
            return True

        batches = await ensure_source_batches(session, source_id=source_id)
        if not batches:
            return False

        pending_rows = (
            (
                await session.execute(
                    select(DiscordPost).where(
                        DiscordPost.source_id == source_id,
                        DiscordPost.batch_id.is_not(None),
                        DiscordPost.post_status != "posted",
                    )
                )
            )
            .scalars()
            .all()
        )
        if pending_rows:
            return True

        posted_batch_ids = {
            row.batch_id
            for row in (
                (
                    await session.execute(
                        select(DiscordPost).where(
                            DiscordPost.source_id == source_id,
                            DiscordPost.batch_id.is_not(None),
                            DiscordPost.post_status == "posted",
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        return any(
            (not batch.posted_to_discord) or (batch.batch_id not in posted_batch_ids)
            for batch in batches
        )
