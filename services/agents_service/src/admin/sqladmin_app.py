from __future__ import annotations

import os
from typing import Any

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from ..database.sqlalchemy_models import (
    Agent,
    AgentEmosConfig,
    ChatHistory,
    ProfileRoom,
    Segment,
    Source,
)


class _EnvAuth(AuthenticationBackend):
    """Very small local-dev auth backend.

    Enabled only when ADMIN_PASSWORD is set. This keeps the admin UI from being
    accidentally exposed without credentials.
    """

    async def login(self, request: Request) -> bool:  # type: ignore[override]
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        expected_user = os.getenv("ADMIN_USERNAME", "admin")
        expected_pass = os.getenv("ADMIN_PASSWORD", "")
        if expected_pass and username == expected_user and password == expected_pass:
            request.session.update({"bt_admin": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:  # type: ignore[override]
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:  # type: ignore[override]
        expected_pass = os.getenv("ADMIN_PASSWORD", "")
        if not expected_pass:
            return False
        return bool(request.session.get("bt_admin"))


class AgentAdmin(ModelView, model=Agent):
    column_list = [
        Agent.id,
        Agent.kind,
        Agent.display_name,
        Agent.matrix_user_id,
        Agent.llm_model,
        Agent.is_active,
    ]


class AgentEmosConfigAdmin(ModelView, model=AgentEmosConfig):
    column_list = [
        AgentEmosConfig.agent_id,
        AgentEmosConfig.tenant_prefix,
        AgentEmosConfig.emos_base_url,
    ]


class ProfileRoomAdmin(ModelView, model=ProfileRoom):
    column_list = [ProfileRoom.agent_id, ProfileRoom.matrix_room_id]


class SourceAdmin(ModelView, model=Source):
    column_list = [Source.id, Source.agent_id, Source.platform, Source.title, Source.emos_group_id]


class SegmentAdmin(ModelView, model=Segment):
    column_list = [
        Segment.id,
        Segment.agent_id,
        Segment.source_id,
        Segment.platform,
        Segment.seq,
        Segment.emos_message_id,
    ]


class ChatHistoryAdmin(ModelView, model=ChatHistory):
    column_list = [
        ChatHistory.id,
        ChatHistory.matrix_room_id,
        ChatHistory.sender_agent_id,
        ChatHistory.modality,
        ChatHistory.created_at,
    ]


def create_admin_app(*, engine: Any) -> Starlette:
    """Create a Starlette app hosting SQLAdmin.

    Returns a mounted sub-app intended to live under `/admin`.
    """

    app = Starlette()

    # Required for SQLAdmin's session-based auth.
    secret_key = os.getenv("ADMIN_SECRET_KEY") or os.getenv("MATRIX_HS_TOKEN") or "dev-secret-key"
    app.add_middleware(SessionMiddleware, secret_key=secret_key)

    authentication_backend: AuthenticationBackend | None = None
    if os.getenv("ADMIN_PASSWORD"):
        authentication_backend = _EnvAuth(secret_key=secret_key)

    admin = Admin(app=app, engine=engine, authentication_backend=authentication_backend)
    admin.add_view(AgentAdmin)
    admin.add_view(AgentEmosConfigAdmin)
    admin.add_view(ProfileRoomAdmin)
    admin.add_view(SourceAdmin)
    admin.add_view(SegmentAdmin)
    admin.add_view(ChatHistoryAdmin)
    return app
