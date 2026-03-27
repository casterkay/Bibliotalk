from __future__ import annotations

import uuid
from datetime import datetime

from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceIngestionState
from bt_store.models_runtime import PlatformPost
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep

router = APIRouter()


@router.get(
    "/agents/{agent_id}/sources",
    dependencies=[Depends(require_admin)],
)
async def list_agent_sources(
    agent_id: uuid.UUID,
    limit: int = 200,
    session: AsyncSession = Depends(session_dep),
) -> dict:
    limit = min(500, max(1, int(limit)))
    rows = (
        await session.execute(
            select(Source, SourceIngestionState)
            .outerjoin(SourceIngestionState, SourceIngestionState.source_id == Source.source_id)
            .where(Source.agent_id == agent_id)
            .order_by(Source.published_at.desc().nullslast(), Source.created_at.desc())
            .limit(limit)
        )
    ).all()
    out = []
    for source, state in rows:
        out.append(
            {
                "source_id": str(source.source_id),
                "agent_id": str(source.agent_id),
                "subscription_id": str(source.subscription_id) if source.subscription_id else None,
                "content_platform": source.content_platform,
                "external_id": source.external_id,
                "external_url": source.external_url,
                "title": source.title,
                "author": source.author or source.channel_name,
                "published_at": source.published_at.isoformat() if source.published_at else None,
                "emos_group_id": source.emos_group_id,
                "meta_synced_at": source.meta_synced_at.isoformat()
                if source.meta_synced_at
                else None,
                "created_at": source.created_at.isoformat() if source.created_at else None,
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
    return {"sources": out}


@router.get(
    "/sources/{source_id}",
    dependencies=[Depends(require_admin)],
)
async def get_source(source_id: uuid.UUID, session: AsyncSession = Depends(session_dep)) -> dict:
    row = (
        await session.execute(
            select(Source, SourceIngestionState)
            .outerjoin(SourceIngestionState, SourceIngestionState.source_id == Source.source_id)
            .where(Source.source_id == source_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source, state = row
    posts = (
        (
            await session.execute(
                select(func.count(PlatformPost.post_id)).where(PlatformPost.source_id == source_id)
            )
        )
        .scalars()
        .first()
    ) or 0
    return {
        "source": {
            "source_id": str(source.source_id),
            "agent_id": str(source.agent_id),
            "subscription_id": str(source.subscription_id) if source.subscription_id else None,
            "content_platform": source.content_platform,
            "external_id": source.external_id,
            "external_url": source.external_url,
            "title": source.title,
            "published_at": source.published_at.isoformat() if source.published_at else None,
            "emos_group_id": source.emos_group_id,
            "raw_meta": source.raw_meta_json or None,
            "ingestion": {
                "ingest_status": state.ingest_status if state else None,
                "failure_count": int(state.failure_count) if state else 0,
                "skip_reason": state.skip_reason if state else None,
                "manual_requested_at": state.manual_requested_at.isoformat()
                if (state and state.manual_requested_at)
                else None,
                "updated_at": state.updated_at.isoformat()
                if (state and state.updated_at)
                else None,
            },
            "platform_posts_count": int(posts),
        }
    }


@router.delete(
    "/sources/{source_id}/posts",
    dependencies=[Depends(require_admin)],
)
async def delete_platform_posts_for_source(
    source_id: uuid.UUID, session: AsyncSession = Depends(session_dep)
) -> dict:
    # Local convenience for operators; does not touch Discord itself.
    deleted = await session.execute(delete(PlatformPost).where(PlatformPost.source_id == source_id))
    await session.commit()
    return {"ok": True, "deleted": int(deleted.rowcount or 0)}


@router.post(
    "/sources/{source_id}/requeue",
    dependencies=[Depends(require_admin)],
)
async def requeue_source(
    source_id: uuid.UUID, session: AsyncSession = Depends(session_dep)
) -> dict:
    now = datetime.utcnow()
    state = await session.get(SourceIngestionState, source_id)
    if state is None:
        state = SourceIngestionState(source_id=source_id)
        session.add(state)
    state.ingest_status = "pending"
    state.next_retry_at = None
    state.updated_at = now
    await session.commit()
    return {"ok": True}
