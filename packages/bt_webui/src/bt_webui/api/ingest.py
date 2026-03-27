from __future__ import annotations

import os

import httpx
from bt_store.models_core import Agent
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep
from ..models import IngestBatchRequest, IngestVideoRequest
from ..settings import load_webui_settings

router = APIRouter()


def _admin_token() -> str:
    token = (os.getenv("BIBLIOTALK_ADMIN_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing BIBLIOTALK_ADMIN_TOKEN")
    return token


async def _resolve_agent_slug(session: AsyncSession, agent_id) -> str:
    agent = (
        (await session.execute(select(Agent).where(Agent.agent_id == agent_id))).scalars().first()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.slug


@router.post("/ingest/video", dependencies=[Depends(require_admin)])
async def ingest_video(
    body: IngestVideoRequest, session: AsyncSession = Depends(session_dep)
) -> dict:
    agent_slug = await _resolve_agent_slug(session, body.agent_id)
    settings = load_webui_settings()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.memories_service_url}/v1/ingest",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"agent_slug": agent_slug, "url": body.url, "title": body.title},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.post("/ingest/batch", dependencies=[Depends(require_admin)])
async def ingest_batch(
    body: IngestBatchRequest, session: AsyncSession = Depends(session_dep)
) -> dict:
    urls = [u.strip() for u in (body.urls or []) if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Provide urls[]")

    agent_slug = await _resolve_agent_slug(session, body.agent_id)
    settings = load_webui_settings()
    async with httpx.AsyncClient(timeout=240.0) as client:
        resp = await client.post(
            f"{settings.memories_service_url}/v1/ingest-batch",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"agent_slug": agent_slug, "urls": urls, "max_items": body.max_items},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()
