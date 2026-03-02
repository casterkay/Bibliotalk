"""Matrix-style message handling for ghost responses."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Awaitable, Callable
from uuid import UUID

from ..database.supabase_helpers import SupabaseHelpers
from ..models.citation import Citation
from .guards import RateLimiter

AgentResolver = Callable[[str], Awaitable[Any]]
SendMessage = Callable[[str, str, dict[str, Any]], Awaitable[str | None]]
SaveHistory = Callable[[dict[str, Any]], Awaitable[None]]
JoinRoom = Callable[[str, str], Awaitable[None]]

_BT_USER_RE = re.compile(r"@bt[^\s:]+:[^\s]+")


class _RoomGhostIndex:
    """Best-effort in-memory room → ghost mapping.

    Synapse appservice transactions do not guarantee replay of room state on
    restart. We track membership changes while running to support DM routing
    (when no explicit mention is present).
    """

    def __init__(self) -> None:
        self._room_to_agents: dict[str, set[str]] = {}

    def add(self, room_id: str, agent_id: str) -> None:
        self._room_to_agents.setdefault(room_id, set()).add(agent_id)

    def discard(self, room_id: str, agent_id: str) -> None:
        agents = self._room_to_agents.get(room_id)
        if not agents:
            return
        agents.discard(agent_id)
        if not agents:
            self._room_to_agents.pop(room_id, None)

    def single_agent(self, room_id: str) -> str | None:
        agents = self._room_to_agents.get(room_id)
        if not agents or len(agents) != 1:
            return None
        return next(iter(agents))


class AppServiceHandler:
    def __init__(
        self,
        *,
        agent_resolver: AgentResolver,
        send_message: SendMessage,
        join_room: JoinRoom,
        supabase_helpers: SupabaseHelpers,
        save_history: SaveHistory | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.agent_resolver = agent_resolver
        self.send_message = send_message
        self.join_room = join_room
        self.supabase_helpers = supabase_helpers
        self.save_history = save_history
        self.rate_limiter = rate_limiter or RateLimiter(cooldown_seconds=5)
        self._ghost_index = _RoomGhostIndex()

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        room_id = str(event.get("room_id") or "")
        if not room_id:
            return None

        event_type = event.get("type")
        if event_type == "m.room.member":
            await self._handle_membership(event)
            return None

        if event_type != "m.room.message":
            return None

        if await self.supabase_helpers.is_profile_room(room_id):
            return None

        content = event.get("content", {}) or {}
        msgtype = str(content.get("msgtype") or "")
        if msgtype not in {"m.text", "m.notice"}:
            return None

        relates_to = content.get("m.relates_to") or {}
        if isinstance(relates_to, dict) and relates_to.get("rel_type") == "m.replace":
            return None

        body = str(content.get("body") or "").strip()
        if not body:
            return None

        sender = str(event.get("sender") or "")
        if sender.startswith("@bt"):
            # Prevent bot loops.
            return None

        agent_id = await self._resolve_addressed_agent_id(room_id, body, content)
        if not agent_id:
            return None

        if not self.rate_limiter.allow(room_id):
            return None

        agent = await self.agent_resolver(agent_id)
        if not getattr(agent, "is_active", True):
            return None

        if self.save_history is not None:
            await self.save_history(
                {
                    "matrix_room_id": room_id,
                    "sender_agent_id": None,
                    "sender_matrix_user_id": sender,
                    "matrix_event_id": event.get("event_id"),
                    "modality": "text",
                    "content": body,
                    "citations": [],
                }
            )

        response = await agent.run(body)
        payload = format_ghost_response(response["text"], response["citations"])

        ghost_user_id = getattr(agent, "matrix_user_id", None)
        if not ghost_user_id:
            row = await self.supabase_helpers.get_agent(UUID(agent_id))
            ghost_user_id = row.get("matrix_user_id") if row else None
        if not ghost_user_id:
            return None

        event_id = await self.send_message(room_id, ghost_user_id, payload)

        if self.save_history is not None:
            await self.save_history(
                {
                    "matrix_room_id": room_id,
                    "sender_agent_id": agent_id,
                    "sender_matrix_user_id": ghost_user_id,
                    "matrix_event_id": event_id,
                    "modality": "text",
                    "content": response["text"],
                    "citations": payload["com.bibliotalk.citations"]["items"],
                }
            )

        return payload

    async def _handle_membership(self, event: dict[str, Any]) -> None:
        room_id = str(event.get("room_id") or "")
        state_key = str(event.get("state_key") or "")
        if not room_id or not state_key.startswith("@bt"):
            return

        content = event.get("content", {}) or {}
        membership = str(content.get("membership") or "")

        agent_row = await self.supabase_helpers.get_agent_by_matrix_id(state_key)
        if not agent_row:
            return
        agent_id = str(agent_row["id"])

        if membership == "invite":
            await self.join_room(room_id, state_key)
            return

        if membership == "join":
            self._ghost_index.add(room_id, agent_id)
            return

        if membership in {"leave", "ban"}:
            self._ghost_index.discard(room_id, agent_id)

    async def _resolve_addressed_agent_id(
        self, room_id: str, body: str, content: dict[str, Any]
    ) -> str | None:
        mentions = content.get("m.mentions") or {}
        mentioned_user_ids = mentions.get("user_ids") or []
        if isinstance(mentioned_user_ids, list):
            for user_id in mentioned_user_ids:
                if not isinstance(user_id, str) or not user_id.startswith("@bt"):
                    continue
                row = await self.supabase_helpers.get_agent_by_matrix_id(user_id)
                if row:
                    return str(row["id"])

        for user_id in _BT_USER_RE.findall(body):
            row = await self.supabase_helpers.get_agent_by_matrix_id(user_id)
            if row:
                return str(row["id"])

        return self._ghost_index.single_agent(room_id)


def format_ghost_response(text: str, citations: list[Citation]) -> dict[str, Any]:
    marker_text = str(text or "").strip()
    for citation in citations:
        marker = f"[^{citation.index}]"
        if marker not in marker_text:
            marker_text = (marker_text + " " + marker).strip()

    source_lines = ["", "──────────", "Sources:"]
    html_sources = ["<hr><b>Sources:</b><br>"]

    for citation in citations:
        source_lines.append(
            f"[{citation.index}] {citation.source_title} ({citation.platform})"
        )
        html_sources.append(
            f'[{citation.index}] <a href="{escape(citation.source_url)}">{escape(citation.source_title)}</a><br>'
        )

    html_text = escape(marker_text)
    for citation in citations:
        html_text = html_text.replace(
            escape(f"[^{citation.index}]"), f"<sup>[{citation.index}]</sup>"
        )

    return {
        "msgtype": "m.text",
        "body": "\n".join([marker_text, *source_lines]),
        "format": "org.matrix.custom.html",
        "formatted_body": f"{html_text}{''.join(html_sources)}",
        "com.bibliotalk.citations": {
            "version": "1",
            "items": [citation.model_dump(mode="json") for citation in citations],
        },
    }
