"""Litestar entrypoint for Synapse appservice transactions."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
from bt_common.config import get_settings
from bt_common.logging import get_request_logger, set_correlation_id
from litestar import HttpMethod, Litestar, Request, Response, asgi, get, route
from litestar.exceptions import ClientException, NotAuthorizedException, NotFoundException
from litestar.openapi import OpenAPIConfig
from litestar.status_codes import HTTP_400_BAD_REQUEST
from litestar.types import Receive, Scope, Send
from pydantic import ValidationError
from starlette.responses import PlainTextResponse

from .admin.sqladmin_app import create_admin_app
from .agent.agent_factory import LLMRegistry, create_ghost_agent
from .database.sqlalchemy_store import SQLAlchemyStore, SQLAlchemyStoreConfig, default_sqlite_url
from .database.store import Store
from .matrix.appservice import AppServiceHandler
from .matrix.client import MatrixClient
from .matrix.events import AppserviceTransaction

logger = get_request_logger("agents_service.server")

_admin_app: object | None = None


def _require_hs_token(request: Request, *, hs_token: str) -> None:
    token = request.query_params.get("access_token")
    if not token:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if token != hs_token:
        raise NotAuthorizedException(detail="invalid access token")


@get("/")
async def index() -> dict[str, object]:
    return {
        "service": "bibliotalk-agents-service",
        "status": "ok",
        "links": {
            "health": "/health",
            "admin": "/admin",
            "openapi_schema": "/schema",
            "openapi_docs": "/docs",
        },
    }


@get("/favicon.ico")
async def favicon() -> Response[None]:
    return Response(None, status_code=204)


@get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@route(
    path="/_matrix/app/v1/transactions/{txn_id:str}",
    http_method=[HttpMethod.PUT, HttpMethod.POST],
)
async def transaction(txn_id: str, request: Request, data: dict[str, object]) -> dict[str, object]:
    settings = get_settings()
    _require_hs_token(request, hs_token=settings.MATRIX_HS_TOKEN)
    set_correlation_id(txn_id)

    handler: AppServiceHandler = request.app.state.handler
    try:
        txn = AppserviceTransaction.model_validate(data)
    except ValidationError as exc:
        raise ClientException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="invalid transaction payload",
        ) from exc

    delivered = 0
    errors = 0
    for event in txn.events:
        try:
            payload = await handler.handle_event(event)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            errors += 1
            logger.exception(
                "handle_event failed event_type=%s room_id=%s",
                getattr(event, "type", None),
                getattr(event, "room_id", None),
            )
            continue
        if payload is not None:
            delivered += 1

    return {"ok": True, "processed": len(txn.events), "delivered": delivered, "errors": errors}


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


@asgi("/admin", is_mount=True, copy_scope=True)
async def admin_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    # Mounted under `/admin`. Returns 404 when not configured.
    if _admin_app is None:
        resp = PlainTextResponse(
            "Admin is not configured (set ADMIN_PASSWORD).",
            status_code=404,
        )
        await resp(scope, receive, send)
        return
    await _admin_app(scope, receive, send)  # type: ignore[misc]


async def _on_startup(app: Litestar) -> None:
    settings = get_settings()
    LLMRegistry.init_defaults()

    database_url = settings.DATABASE_URL or default_sqlite_url()
    store = SQLAlchemyStore(
        config=SQLAlchemyStoreConfig(database_url=database_url, create_all=True)
    )
    await store.init()

    global _admin_app
    if os.getenv("ADMIN_PASSWORD"):
        _admin_app = create_admin_app(engine=store.engine)

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

    async def _send_message(room_id: str, user_id: str, payload: dict[str, object]) -> str | None:
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
    logger.info("startup complete db=%s", store.database_url)


async def _on_shutdown(app: Litestar) -> None:
    matrix_client: MatrixClient | None = getattr(app.state, "matrix_client", None)
    if matrix_client is not None:
        await matrix_client.aclose()
    store: Store | None = getattr(app.state, "store", None)
    if store is not None:
        await store.aclose()


app = Litestar(
    route_handlers=[
        index,
        favicon,
        health,
        transaction,
        appservice_user_query,
        admin_asgi,
    ],
    on_startup=[_on_startup],
    on_shutdown=[_on_shutdown],
    openapi_config=OpenAPIConfig(
        title="Bibliotalk Agent Service",
        version="0.1.0",
    ),
)
