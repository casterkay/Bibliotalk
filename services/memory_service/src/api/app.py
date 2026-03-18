from __future__ import annotations

from bt_common.config import get_settings
from bt_common.evermemos_client import EverMemOSClient
from bt_store.engine import get_session_factory, init_database
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ..adapters.rss_feed import canonicalize_http_url, extract_youtube_video_id
from ..adapters.youtube_transcript import load_youtube_transcript_source
from ..domain.errors import AdapterError
from ..ops import request_manual_ingest
from ..pipeline.discovery import discover_subscription
from ..pipeline.index import IngestionIndex
from ..pipeline.ingest import ingest_source
from ..runtime.reporting import configure_logging
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
    app = FastAPI(title="Bibliotalk Memories API")
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

    @app.on_event("startup")
    async def _startup() -> None:
        await init_database(config.db_path)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await client.aclose()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/memories/{memory_id}")
    async def memory_html(memory_id: str) -> HTMLResponse:
        try:
            view = await svc.get_memcell_view_by_id(memory_id)
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
    async def ingest(req: IngestRequest) -> dict:
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
    async def ingest_batch(req: IngestBatchRequest) -> EnqueueSummary:
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
    async def subscribe(req: SubscribeRequest) -> dict:
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

    return app
