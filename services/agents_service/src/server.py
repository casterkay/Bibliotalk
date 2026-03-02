"""FastAPI entrypoint for Synapse appservice transactions."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
from bt_common.config import get_settings
from bt_common.logging import get_request_logger, set_correlation_id
from fastapi import FastAPI, HTTPException, Request
from supabase import create_async_client

from .agent.agent_factory import LLMRegistry, create_ghost_agent
from .database.supabase_helpers import SupabaseHelpers
from .matrix.appservice import AppServiceHandler
from .matrix.client import MatrixClient

app = FastAPI(title="Bibliotalk Agent Service")
logger = get_request_logger("agents_service.server")


@app.on_event("startup")
async def startup() -> None:
    settings = get_settings()
    LLMRegistry.init_defaults()

    supabase_client = await create_async_client(
        settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
    )
    supabase_helpers = SupabaseHelpers(client=supabase_client)

    matrix_http = httpx.AsyncClient(timeout=15.0)
    matrix_client = MatrixClient(
        homeserver_url=settings.MATRIX_HOMESERVER_URL,
        as_token=settings.MATRIX_AS_TOKEN,
        http_client=matrix_http,
    )

    async def _resolve_agent(agent_id: str):
        return await create_ghost_agent(
            UUID(agent_id), supabase_helpers=supabase_helpers, llm_registry=LLMRegistry
        )

    async def _join_room(room_id: str, user_id: str) -> None:
        await matrix_client.join_room_as(room_id=room_id, user_id=user_id)

    async def _send_message(room_id: str, user_id: str, payload: dict[str, Any]) -> str | None:
        result = await matrix_client.send_message_as(
            room_id=room_id, user_id=user_id, content=payload, txn_id=str(uuid4())
        )
        return result.event_id or None

    handler = AppServiceHandler(
        agent_resolver=_resolve_agent,
        send_message=_send_message,
        join_room=_join_room,
        supabase_helpers=supabase_helpers,
        save_history=supabase_helpers.save_chat_history,
    )

    app.state.settings = settings
    app.state.supabase_client = supabase_client
    app.state.supabase_helpers = supabase_helpers
    app.state.matrix_client = matrix_client
    app.state.handler = handler

    logger.info("startup complete")


@app.on_event("shutdown")
async def shutdown() -> None:
    matrix_client: MatrixClient | None = getattr(app.state, "matrix_client", None)
    if matrix_client is not None:
        await matrix_client.aclose()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _require_hs_token(request: Request) -> None:
    settings = app.state.settings
    token = request.query_params.get("access_token")
    if not token:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if token != settings.MATRIX_HS_TOKEN:
        raise HTTPException(status_code=401, detail="invalid access token")


@app.put("/_matrix/app/v1/transactions/{txn_id}")
@app.post("/_matrix/app/v1/transactions/{txn_id}")
async def transaction(txn_id: str, body: dict, request: Request) -> dict[str, object]:
    _require_hs_token(request)
    set_correlation_id(txn_id)
    handler: AppServiceHandler = app.state.handler

    events = body.get("events", [])
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="invalid events payload")

    delivered = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            payload = await handler.handle_event(event)
            if payload is not None:
                delivered += 1
        except Exception:  # noqa: BLE001
            logger.exception("handle_event failed event_type=%s", event.get("type"))
            continue

    return {"ok": True, "processed": len(events), "delivered": delivered}
