from __future__ import annotations

from contextlib import asynccontextmanager

from bt_common.config import get_settings
from bt_common.evermemos_client import EverMemOSClient
from bt_store.engine import get_session_factory, init_database
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ..adapters.rss_feed import canonicalize_http_url, extract_youtube_video_id
from ..adapters.youtube_transcript import load_youtube_transcript_source
from ..domain.errors import AdapterError
from ..ops import request_manual_ingest
from ..pipeline.discovery import discover_subscription
from ..pipeline.index import IngestionIndex
from ..pipeline.ingest import ingest_source
from ..runtime.reporting import configure_logging
from .admin_auth import require_admin
from .admin_console import create_admin_console_router
from .admin_models import CollectorRunOnceRequest
from .config import MemoriesApiRuntimeConfig
from .html import render_memcell_html
from .memories_service import MemoriesService
from .memories_store import MemoriesStore
from .models import (
    ApiChunk,
    ApiLinks,
    ApiMemCellRecord,
    ApiSource,
    EnqueueSummary,
    IngestBatchRequest,
    IngestRequest,
    SearchResponse,
    SubscribeRequest,
)


def create_app(
    config: MemoriesApiRuntimeConfig,
    *,
    evermemos_client: EverMemOSClient | None = None,
) -> FastAPI:
    logger = configure_logging(level=config.log_level)

    session_factory = get_session_factory(config.db_path)
    store = MemoriesStore(session_factory)
    client = evermemos_client or EverMemOSClient(
        config.emos_base_url,
        api_key=config.emos_api_key,
        timeout=config.emos_timeout_s,
        retries=config.emos_retries,
    )
    settings = get_settings()
    svc = MemoriesService(
        store=store, evermemos_client=client, public_base_url=settings.BIBLIOTALK_WEB_URL
    )

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        await init_database(config.db_path)
        try:
            yield
        finally:
            await client.aclose()

    app = FastAPI(title="Bibliotalk Memories API", lifespan=_lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(
        create_admin_console_router(session_factory, evermemos_client=client),
        prefix="/v1/admin",
    )

    @app.get("/memories/{memory_id}")
    async def memory_html(memory_id: str) -> HTMLResponse:
        try:
            view = await svc.get_memcell_view_by_id(memory_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        links = svc.build_links(view)
        record = ApiMemCellRecord(
            id=view.memory_id,
            agent_slug=view.agent_slug,
            source_id=view.source.source_id,
            timestamp=view.timestamp,
            memcell=view.memcell,
            source=ApiSource(
                source_id=view.source.source_id,
                agent_slug=view.source.agent_slug,
                platform=view.source.platform,
                external_id=view.source.external_id,
                title=view.source.title,
                url=view.source.url,
                published_at=view.source.published_at,
            ),
            chunks=[
                ApiChunk(
                    segment_id=chunk.segment_id,
                    seq=chunk.seq,
                    timestamp=chunk.timestamp,
                    text=chunk.text,
                    start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms,
                )
                for chunk in view.chunks
            ],
            links=ApiLinks(html=str(links["html"]), video_at_timepoint=links["video_at_timepoint"]),
        )
        return HTMLResponse(content=render_memcell_html(record), status_code=200)

    @app.get("/v1/memories", response_model=list[ApiMemCellRecord])
    async def memories_json(
        *,
        id: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ApiMemCellRecord]:
        if bool(id) == bool(source_id):
            raise HTTPException(
                status_code=400, detail="Provide exactly one of `id` or `source_id`."
            )

        try:
            if id:
                view = await svc.get_memcell_view_by_id(id)
                views = [view]
            else:
                views = await svc.list_source_memcells(
                    source_id=str(source_id),
                    limit=min(500, max(1, int(limit))),
                    offset=max(0, int(offset)),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        out: list[ApiMemCellRecord] = []
        for view in views:
            links = svc.build_links(view)
            out.append(
                ApiMemCellRecord(
                    id=view.memory_id,
                    agent_slug=view.agent_slug,
                    source_id=view.source.source_id,
                    timestamp=view.timestamp,
                    memcell=view.memcell,
                    source=ApiSource(
                        source_id=view.source.source_id,
                        agent_slug=view.source.agent_slug,
                        platform=view.source.platform,
                        external_id=view.source.external_id,
                        title=view.source.title,
                        url=view.source.url,
                        published_at=view.source.published_at,
                    ),
                    chunks=[
                        ApiChunk(
                            segment_id=chunk.segment_id,
                            seq=chunk.seq,
                            timestamp=chunk.timestamp,
                            text=chunk.text,
                            start_ms=chunk.start_ms,
                            end_ms=chunk.end_ms,
                        )
                        for chunk in view.chunks
                    ],
                    links=ApiLinks(
                        html=str(links["html"]),
                        video_at_timepoint=links["video_at_timepoint"],
                    ),
                )
            )
        return out

    @app.get("/v1/search", response_model=SearchResponse)
    async def search(
        *,
        agent_slug: str,
        q: str,
        top_k: int = 8,
        retrieve_method: str = "rrf",
    ) -> SearchResponse:
        allowed_methods = {"keyword", "vector", "hybrid", "rrf", "agentic"}
        if retrieve_method not in allowed_methods:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported retrieve_method: {retrieve_method}. allowed={sorted(allowed_methods)}",
            )
        views = await svc.search(
            agent_slug=agent_slug,
            query=q,
            retrieve_method=retrieve_method,
            top_k=min(50, max(1, int(top_k))),
        )
        result_records: list[ApiMemCellRecord] = []
        for view in views:
            links = svc.build_links(view)
            result_records.append(
                ApiMemCellRecord(
                    id=view.memory_id,
                    agent_slug=view.agent_slug,
                    source_id=view.source.source_id,
                    timestamp=view.timestamp,
                    memcell=view.memcell,
                    source=ApiSource(
                        source_id=view.source.source_id,
                        agent_slug=view.source.agent_slug,
                        platform=view.source.platform,
                        external_id=view.source.external_id,
                        title=view.source.title,
                        url=view.source.url,
                        published_at=view.source.published_at,
                    ),
                    chunks=[
                        ApiChunk(
                            segment_id=chunk.segment_id,
                            seq=chunk.seq,
                            timestamp=chunk.timestamp,
                            text=chunk.text,
                            start_ms=chunk.start_ms,
                            end_ms=chunk.end_ms,
                        )
                        for chunk in view.chunks
                    ],
                    links=ApiLinks(
                        html=str(links["html"]),
                        video_at_timepoint=links["video_at_timepoint"],
                    ),
                )
            )
        return SearchResponse(results=result_records, retrieve_method=retrieve_method)

    @app.post("/v1/ingest")
    async def ingest(req: IngestRequest, _: None = Depends(require_admin)) -> dict:
        try:
            canon = canonicalize_http_url(req.url)
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        video_id = extract_youtube_video_id(canon)
        if not video_id:
            raise HTTPException(status_code=400, detail="Only YouTube video URLs are supported.")

        try:
            source_content = await load_youtube_transcript_source(
                user_id=req.agent_slug,
                external_id=video_id,
                title=req.title or f"(manual ingest) {video_id}",
                video_id=video_id,
                source_url=canon,
            )
            report = await ingest_source(
                source_content=source_content,
                index=IngestionIndex(session_factory, path=config.index_path),
                client=client,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("inline ingest failed agent=%s url=%s", req.agent_slug, canon)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return report.model_dump()

    @app.post("/v1/ingest-batch", response_model=EnqueueSummary, status_code=202)
    async def ingest_batch(
        req: IngestBatchRequest, _: None = Depends(require_admin)
    ) -> EnqueueSummary:
        urls = []
        if req.url:
            urls.append(req.url)
        if req.urls:
            urls.extend(req.urls)
        urls = [u for u in (u.strip() for u in urls) if u]
        if not urls:
            raise HTTPException(status_code=400, detail="Provide `url` or `urls`.")

        enqueued: list[str] = []
        skipped = 0
        errors: list[str] = []
        max_items = req.max_items

        for raw in urls:
            try:
                canon = canonicalize_http_url(raw)
            except Exception as exc:
                errors.append(f"{raw}: {exc}")
                continue

            try:
                discovered = await discover_subscription(canon, bootstrap=True)
            except Exception as exc:
                errors.append(f"{canon}: discovery failed ({exc})")
                continue

            if max_items is not None:
                discovered = discovered[:max_items]

            if not discovered:
                skipped += 1
                continue

            for item in discovered:
                try:
                    await request_manual_ingest(
                        db_path=str(config.db_path),
                        agent_slug=req.agent_slug,
                        external_id=item.video_id,
                        title=item.title,
                        source_url=item.source_url,
                        platform="youtube",
                    )
                    enqueued.append(f"{req.agent_slug}:youtube:{item.video_id}")
                except Exception as exc:
                    errors.append(f"{item.source_url}: enqueue failed ({exc})")

        return EnqueueSummary(
            enqueued_sources=len(enqueued),
            enqueued_source_ids=enqueued,
            skipped_sources=skipped,
            errors=errors,
        )

    @app.post("/v1/subscribe")
    async def subscribe(req: SubscribeRequest, _: None = Depends(require_admin)) -> dict:
        from bt_store.models_core import Agent
        from bt_store.models_ingestion import Subscription, SubscriptionState
        from sqlalchemy import select

        try:
            canon = canonicalize_http_url(req.subscription_url)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async with session_factory() as session:
            agent = (
                (await session.execute(select(Agent).where(Agent.slug == req.agent_slug)))
                .scalars()
                .first()
            )
            if agent is None:
                raise HTTPException(status_code=404, detail=f"Unknown agent: {req.agent_slug}")

            existing = (
                (
                    await session.execute(
                        select(Subscription).where(
                            Subscription.agent_id == agent.agent_id,
                            Subscription.content_platform == req.content_platform,
                            Subscription.subscription_type == req.subscription_type,
                            Subscription.subscription_url == canon,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is None:
                existing = Subscription(
                    agent_id=agent.agent_id,
                    content_platform=req.content_platform,
                    subscription_type=req.subscription_type,
                    subscription_url=canon,
                    poll_interval_minutes=int(req.poll_interval_minutes),
                    is_active=True,
                )
                session.add(existing)
                await session.flush()
                session.add(SubscriptionState(subscription_id=existing.subscription_id))
            else:
                existing.is_active = True
                existing.poll_interval_minutes = int(req.poll_interval_minutes)

            await session.commit()

        return {
            "subscription_id": str(existing.subscription_id),
            "agent_slug": req.agent_slug,
            "content_platform": req.content_platform,
            "subscription_type": req.subscription_type,
            "subscription_url": canon,
            "poll_interval_minutes": req.poll_interval_minutes,
        }

    @app.post("/v1/admin/collector/run-once")
    async def admin_collector_run_once(
        body: CollectorRunOnceRequest, _: None = Depends(require_admin)
    ) -> dict:
        from datetime import UTC, datetime

        from bt_store.models_core import Agent
        from bt_store.models_evidence import Source
        from bt_store.models_ingestion import SourceIngestionState, Subscription, SubscriptionState
        from sqlalchemy import select

        from ..runtime.config import load_runtime_config
        from ..runtime.poller import CollectorPoller

        now = datetime.now(tz=UTC)
        agent_slug = (body.agent_slug or "").strip() or None

        async def _snapshot_subscriptions() -> list[dict]:
            async with session_factory() as session:
                stmt = (
                    select(Subscription, SubscriptionState, Agent)
                    .join(Agent, Agent.agent_id == Subscription.agent_id)
                    .outerjoin(
                        SubscriptionState,
                        SubscriptionState.subscription_id == Subscription.subscription_id,
                    )
                    .order_by(Agent.slug, Subscription.created_at.desc())
                )
                if agent_slug:
                    stmt = stmt.where(Agent.slug == agent_slug)
                rows = (await session.execute(stmt)).all()

            out: list[dict] = []
            for sub, state, agent in rows:
                out.append(
                    {
                        "agent_slug": agent.slug,
                        "subscription_id": str(sub.subscription_id),
                        "subscription_url": sub.subscription_url,
                        "subscription_type": sub.subscription_type,
                        "content_platform": sub.content_platform,
                        "poll_interval_minutes": sub.poll_interval_minutes,
                        "is_active": bool(sub.is_active),
                        "state": {
                            "last_seen_external_id": state.last_seen_external_id if state else None,
                            "last_published_at": state.last_published_at.isoformat()
                            if (state and state.last_published_at)
                            else None,
                            "last_polled_at": state.last_polled_at.isoformat()
                            if (state and state.last_polled_at)
                            else None,
                            "failure_count": int(state.failure_count) if state else 0,
                            "next_retry_at": state.next_retry_at.isoformat()
                            if (state and state.next_retry_at)
                            else None,
                            "updated_at": state.updated_at.isoformat()
                            if (state and state.updated_at)
                            else None,
                        },
                    }
                )
            return out

        subscriptions_before = await _snapshot_subscriptions()

        runtime_config = load_runtime_config(
            db_path=str(config.db_path),
            agent_slug=agent_slug,
            log_level=config.log_level,
            emos_base_url=config.emos_base_url,
            emos_api_key=config.emos_api_key,
            index_path=str(config.index_path),
        )
        poller = CollectorPoller(
            config=runtime_config,
            session_factory=session_factory,
            logger=logger,
            client=client,
        )
        snapshot = await poller.run_once()
        subscriptions_after = await _snapshot_subscriptions()

        async with session_factory() as session:
            src_stmt = (
                select(Source, SourceIngestionState, Agent)
                .join(Agent, Agent.agent_id == Source.agent_id)
                .outerjoin(
                    SourceIngestionState,
                    SourceIngestionState.source_id == Source.source_id,
                )
                .order_by(Source.created_at.desc())
                .limit(200)
            )
            if agent_slug:
                src_stmt = src_stmt.where(Agent.slug == agent_slug)
            src_rows = (await session.execute(src_stmt)).all()

        recent_sources: list[dict] = []
        for source, state, agent in src_rows:
            recent_sources.append(
                {
                    "agent_slug": agent.slug,
                    "source_id": str(source.source_id),
                    "content_platform": source.content_platform,
                    "external_id": source.external_id,
                    "external_url": source.external_url,
                    "title": source.title,
                    "published_at": source.published_at.isoformat()
                    if source.published_at
                    else None,
                    "emos_group_id": source.emos_group_id,
                    "ingestion": {
                        "ingest_status": state.ingest_status if state else None,
                        "failure_count": int(state.failure_count) if state else 0,
                        "last_attempt_at": state.last_attempt_at.isoformat()
                        if (state and state.last_attempt_at)
                        else None,
                        "next_retry_at": state.next_retry_at.isoformat()
                        if (state and state.next_retry_at)
                        else None,
                        "skip_reason": state.skip_reason if state else None,
                        "manual_requested_at": state.manual_requested_at.isoformat()
                        if (state and state.manual_requested_at)
                        else None,
                        "updated_at": state.updated_at.isoformat()
                        if (state and state.updated_at)
                        else None,
                    },
                }
            )

        return {
            "ok": True,
            "requested_agent_slug": agent_slug,
            "generated_at": now.isoformat(),
            "poller_snapshot": {
                "active_subscriptions": snapshot.active_subscriptions,
                "agent_slug": snapshot.agent_slug,
                "discovered_videos": snapshot.discovered_videos,
                "ingested_videos": snapshot.ingested_videos,
                "failed_subscriptions": snapshot.failed_subscriptions,
            },
            "subscriptions_before": subscriptions_before,
            "subscriptions_after": subscriptions_after,
            "recent_sources": recent_sources,
        }

    @app.delete("/v1/admin/sources/{source_id}")
    async def admin_delete_source(source_id: str, _: None = Depends(require_admin)) -> dict:
        from datetime import UTC, datetime
        from uuid import UUID

        from bt_common.exceptions import EMOSNotFoundError
        from bt_store.models_core import Agent
        from bt_store.models_evidence import Segment, Source
        from bt_store.models_ingestion import SourceIngestionState, SourceTextBatch
        from bt_store.models_runtime import PlatformPost
        from sqlalchemy import delete, func, select

        try:
            source_uuid = UUID(source_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid source_id: {source_id}") from exc

        now = datetime.now(tz=UTC)

        async with session_factory() as session:
            row = (
                await session.execute(
                    select(Source, Agent)
                    .join(Agent, Agent.agent_id == Source.agent_id)
                    .where(Source.source_id == source_uuid)
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="Source not found")
            source, agent = row

            seg_count = (
                (
                    await session.execute(
                        select(func.count(Segment.segment_id)).where(
                            Segment.source_id == source_uuid
                        )
                    )
                )
                .scalars()
                .first()
            ) or 0
            batch_count = (
                (
                    await session.execute(
                        select(func.count(SourceTextBatch.batch_id)).where(
                            SourceTextBatch.source_id == source_uuid
                        )
                    )
                )
                .scalars()
                .first()
            ) or 0
            post_count = (
                (
                    await session.execute(
                        select(func.count(PlatformPost.post_id)).where(
                            PlatformPost.source_id == source_uuid
                        )
                    )
                )
                .scalars()
                .first()
            ) or 0

        emos_deleted = False
        try:
            await client.delete_by_group_id(source.emos_group_id, user_id=agent.slug)
            emos_deleted = True
        except EMOSNotFoundError:
            emos_deleted = False
        except Exception:
            # Continue; local cleanup is still valuable.
            logger.exception("admin delete_by_group_id failed group_id=%s", source.emos_group_id)

        async with session_factory() as session:
            await session.execute(delete(Segment).where(Segment.source_id == source_uuid))
            await session.execute(
                delete(SourceTextBatch).where(SourceTextBatch.source_id == source_uuid)
            )
            await session.execute(delete(PlatformPost).where(PlatformPost.source_id == source_uuid))

            state = await session.get(SourceIngestionState, source_uuid)
            if state is None:
                state = SourceIngestionState(source_id=source_uuid)
                session.add(state)
            state.ingest_status = "deleted"
            state.failure_count = 0
            state.last_attempt_at = None
            state.next_retry_at = None
            state.manual_requested_at = None
            state.skip_reason = "operator_deleted"
            state.updated_at = now
            await session.commit()

        return {
            "ok": True,
            "source_id": source_id,
            "emos_group_id": source.emos_group_id,
            "emos_deleted": emos_deleted,
            "deleted_local": {
                "segments": int(seg_count),
                "batches": int(batch_count),
                "platform_posts": int(post_count),
            },
            "tombstone": {"ingest_status": "deleted", "skip_reason": "operator_deleted"},
        }

    return app
