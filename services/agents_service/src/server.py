"""Litestar entrypoint for Synapse appservice transactions."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
from bt_common.config import get_settings
from bt_common.logging import get_request_logger, set_correlation_id
from litestar import Litestar, Request, get, post, put
from litestar.exceptions import ClientException, NotAuthorizedException, NotFoundException
from litestar.status_codes import HTTP_400_BAD_REQUEST

from .agent.agent_factory import LLMRegistry, create_ghost_agent
from .database.sqlalchemy_store import SQLAlchemyStore, SQLAlchemyStoreConfig, default_sqlite_url
from .database.store import Store
from .matrix.appservice import AppServiceHandler
from .matrix.client import MatrixClient

logger = get_request_logger("agents_service.server")


def _require_hs_token(request: Request, *, hs_token: str) -> None:
    token = request.query_params.get("access_token")
    if not token:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if token != hs_token:
        raise NotAuthorizedException(detail="invalid access token")


@get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@put("/_matrix/app/v1/transactions/{txn_id:str}")
@post("/_matrix/app/v1/transactions/{txn_id:str}")
async def transaction(txn_id: str, request: Request, data: dict[str, Any]) -> dict[str, object]:
    settings = get_settings()
    _require_hs_token(request, hs_token=settings.MATRIX_HS_TOKEN)
    set_correlation_id(txn_id)

    handler: AppServiceHandler = request.app.state.handler
    events = data.get("events", [])
    if not isinstance(events, list):
        raise ClientException(status_code=HTTP_400_BAD_REQUEST, detail="invalid events payload")

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


@get("/_matrix/app/v1/users/{user_id:str}")
async def appservice_user_query(user_id: str, request: Request) -> dict[str, object]:
    """Synapse appservice user query.

    Synapse calls this to ask whether the appservice "owns" a given user ID.
    Return 200 for known Ghost users so Synapse can provision them.
    """

    settings = get_settings()
    _require_hs_token(request, hs_token=settings.MATRIX_HS_TOKEN)

    if not user_id.startswith("@bt_"):
        raise NotFoundException(detail="unknown user")

    store: Store = request.app.state.store
    row = await store.get_agent_by_matrix_id(user_id)
    if not row:
        raise NotFoundException(detail="unknown user")
    return {}


async def _on_startup(app: Litestar) -> None:
    settings = get_settings()
    LLMRegistry.init_defaults()

    database_url = settings.DATABASE_URL or default_sqlite_url()
    store = SQLAlchemyStore(config=SQLAlchemyStoreConfig(database_url=database_url, create_all=True))
    await store.init()

    matrix_http = httpx.AsyncClient(timeout=15.0)
    matrix_client = MatrixClient(
        homeserver_url=settings.MATRIX_HOMESERVER_URL,
        as_token=settings.MATRIX_AS_TOKEN,
        http_client=matrix_http,
    )

    async def _resolve_agent(agent_id: str):
        return await create_ghost_agent(UUID(agent_id), store=store, llm_registry=LLMRegistry)

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
        store=store,
        save_history=store.save_chat_history,
    )

    app.state.settings = settings
    app.state.store = store
    app.state.matrix_client = matrix_client
    app.state.handler = handler
    logger.info("startup complete db=%s", database_url)


async def _on_shutdown(app: Litestar) -> None:
    matrix_client: MatrixClient | None = getattr(app.state, "matrix_client", None)
    if matrix_client is not None:
        await matrix_client.aclose()
    store: Store | None = getattr(app.state, "store", None)
    if store is not None:
        await store.aclose()


app = Litestar(
    route_handlers=[health, transaction, appservice_user_query],
    on_startup=[_on_startup],
    on_shutdown=[_on_shutdown],
    title="Bibliotalk Agent Service",
)
