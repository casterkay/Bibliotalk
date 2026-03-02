"""FastAPI entrypoint for appservice transactions."""

from __future__ import annotations

from uuid import UUID

from bt_common.logging import get_request_logger, set_correlation_id
from fastapi import FastAPI

from .agent.agent_factory import LLMRegistry, create_ghost_agent
from .database.supabase_helpers import SupabaseHelpers
from .matrix.appservice import AppServiceHandler

app = FastAPI(title="Bibliotalk Agent Service")
logger = get_request_logger("agents_service.main")


def _supabase() -> SupabaseHelpers:
    # The real Supabase client should be injected at runtime.
    return SupabaseHelpers(client=None)


async def _resolve_agent(agent_id: str):
    return await create_ghost_agent(
        UUID(agent_id), supabase_helpers=_supabase(), llm_registry=LLMRegistry
    )


async def _send_message(room_id: str, payload: dict):
    logger.info(
        "send_message room_id=%s payload_keys=%s", room_id, list(payload.keys())
    )


handler = AppServiceHandler(agent_resolver=_resolve_agent, send_message=_send_message)


@app.on_event("startup")
async def startup() -> None:
    LLMRegistry.init_defaults()
    logger.info("startup complete")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/_matrix/app/v1/transactions/{txn_id}")
async def transaction(txn_id: str, body: dict) -> dict[str, object]:
    set_correlation_id(txn_id)
    events = body.get("events", [])
    delivered = 0
    for event in events:
        payload = await handler.handle_event(event)
        if payload is not None:
            delivered += 1

    return {"ok": True, "processed": len(events), "delivered": delivered}
