from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


def _ts() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class LiveSession:
    session_id: str
    agent_id: UUID
    platform: str
    room_id: str
    initiator_platform_user_id: str
    modality: str
    active_turn_id: str | None = None
    active_task: asyncio.Task | None = None


class LiveSessionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, LiveSession] = {}

    async def create_session(
        self,
        *,
        agent_id: UUID,
        platform: str,
        room_id: str,
        initiator_platform_user_id: str,
        modality: str,
    ) -> LiveSession:
        async with self._lock:
            session_id = str(uuid4())
            session = LiveSession(
                session_id=session_id,
                agent_id=agent_id,
                platform=platform,
                room_id=room_id,
                initiator_platform_user_id=initiator_platform_user_id,
                modality=modality,
            )
            self._sessions[session_id] = session
            return session

    async def get(self, session_id: str) -> LiveSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def cancel_turn(self, session: LiveSession, *, turn_id: str, reason: str) -> None:
        task = session.active_task
        if task and not task.done() and session.active_turn_id == turn_id:
            task.cancel()
            session.active_task = None
            session.active_turn_id = None
