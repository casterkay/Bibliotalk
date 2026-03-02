from __future__ import annotations

from uuid import uuid4

import pytest
from agents_service.matrix.appservice import AppServiceHandler
from agents_service.models.citation import Citation


class FakeSupabase:
    def __init__(self) -> None:
        self.profile_rooms: set[str] = set()
        self.agents_by_matrix: dict[str, dict] = {}
        self.agents_by_id: dict[str, dict] = {}

    async def is_profile_room(self, matrix_room_id: str) -> bool:
        return matrix_room_id in self.profile_rooms

    async def get_agent_by_matrix_id(self, matrix_user_id: str):
        return self.agents_by_matrix.get(matrix_user_id)

    async def get_agent(self, agent_id):
        return self.agents_by_id.get(str(agent_id))

    async def save_chat_history(self, record: dict):
        return record


class FakeAgent:
    def __init__(self, *, agent_id: str, matrix_user_id: str):
        self.id = agent_id
        self.matrix_user_id = matrix_user_id
        self.is_active = True

    async def run(self, _query: str):
        citation = Citation(
            index=1,
            segment_id=uuid4(),
            emos_message_id="a:b:c:seg:1",
            source_title="The Analects",
            source_url="https://example.com",
            quote="Learning without thought is labor lost.",
            platform="gutenberg",
        )
        return {"text": "Answer [^1]", "citations": [citation]}


@pytest.mark.asyncio
async def test_ignores_profile_rooms() -> None:
    supabase = FakeSupabase()
    supabase.profile_rooms.add("!profile:example")

    async def resolve_agent(_agent_id: str):
        raise AssertionError("agent should not be resolved for profile rooms")

    async def send_message(_room_id: str, _user_id: str, _payload: dict):
        raise AssertionError("should not send")

    async def join_room(_room_id: str, _user_id: str):
        raise AssertionError("should not join")

    handler = AppServiceHandler(
        agent_resolver=resolve_agent,
        send_message=send_message,
        join_room=join_room,
        supabase_helpers=supabase,  # type: ignore[arg-type]
    )

    payload = await handler.handle_event(
        {
            "type": "m.room.message",
            "room_id": "!profile:example",
            "sender": "@alice:example",
            "content": {"msgtype": "m.text", "body": "hi"},
        }
    )

    assert payload is None


@pytest.mark.asyncio
async def test_membership_invite_triggers_join() -> None:
    supabase = FakeSupabase()
    agent_id = str(uuid4())
    ghost_user_id = "@btghost_confucius:example"
    supabase.agents_by_matrix[ghost_user_id] = {"id": agent_id, "matrix_user_id": ghost_user_id}

    seen: dict[str, str] = {}

    async def resolve_agent(_agent_id: str):
        raise AssertionError("not used")

    async def send_message(_room_id: str, _user_id: str, _payload: dict):
        raise AssertionError("not used")

    async def join_room(room_id: str, user_id: str):
        seen["room_id"] = room_id
        seen["user_id"] = user_id

    handler = AppServiceHandler(
        agent_resolver=resolve_agent,
        send_message=send_message,
        join_room=join_room,
        supabase_helpers=supabase,  # type: ignore[arg-type]
    )

    await handler.handle_event(
        {
            "type": "m.room.member",
            "room_id": "!dm:example",
            "state_key": ghost_user_id,
            "sender": "@alice:example",
            "content": {"membership": "invite"},
        }
    )

    assert seen == {"room_id": "!dm:example", "user_id": ghost_user_id}


@pytest.mark.asyncio
async def test_mention_routes_to_correct_ghost_and_sends_as_virtual_user() -> None:
    supabase = FakeSupabase()
    agent_id = str(uuid4())
    ghost_user_id = "@btghost_confucius:example"
    supabase.agents_by_matrix[ghost_user_id] = {"id": agent_id, "matrix_user_id": ghost_user_id}
    supabase.agents_by_id[agent_id] = {"id": agent_id, "matrix_user_id": ghost_user_id}

    resolved: dict[str, str] = {}
    sent: list[tuple[str, str, dict]] = []
    saved: list[dict] = []

    async def resolve_agent(requested_agent_id: str):
        resolved["agent_id"] = requested_agent_id
        return FakeAgent(agent_id=requested_agent_id, matrix_user_id=ghost_user_id)

    async def send_message(room_id: str, user_id: str, payload: dict):
        sent.append((room_id, user_id, payload))
        return "$event"

    async def join_room(_room_id: str, _user_id: str):
        return None

    async def save_history(record: dict):
        saved.append(record)

    handler = AppServiceHandler(
        agent_resolver=resolve_agent,
        send_message=send_message,
        join_room=join_room,
        supabase_helpers=supabase,  # type: ignore[arg-type]
        save_history=save_history,
    )

    payload = await handler.handle_event(
        {
            "type": "m.room.message",
            "room_id": "!room:example",
            "sender": "@alice:example",
            "event_id": "$m1",
            "content": {"msgtype": "m.text", "body": f"hi {ghost_user_id}"},
        }
    )

    assert payload is not None
    assert resolved["agent_id"] == agent_id
    assert sent and sent[0][0] == "!room:example" and sent[0][1] == ghost_user_id
    assert payload["com.bibliotalk.citations"]["items"]
    assert "Sources:" in payload["body"]
    # Saves: one user msg + one ghost msg
    assert len(saved) == 2


@pytest.mark.asyncio
async def test_dm_routing_uses_single_joined_ghost() -> None:
    supabase = FakeSupabase()
    agent_id = str(uuid4())
    ghost_user_id = "@btghost_confucius:example"
    supabase.agents_by_matrix[ghost_user_id] = {"id": agent_id, "matrix_user_id": ghost_user_id}
    supabase.agents_by_id[agent_id] = {"id": agent_id, "matrix_user_id": ghost_user_id}

    async def resolve_agent(_agent_id: str):
        return FakeAgent(agent_id=agent_id, matrix_user_id=ghost_user_id)

    async def send_message(_room_id: str, _user_id: str, _payload: dict):
        return "$event"

    async def join_room(_room_id: str, _user_id: str):
        return None

    handler = AppServiceHandler(
        agent_resolver=resolve_agent,
        send_message=send_message,
        join_room=join_room,
        supabase_helpers=supabase,  # type: ignore[arg-type]
    )

    # Join event populates index.
    await handler.handle_event(
        {
            "type": "m.room.member",
            "room_id": "!dm:example",
            "state_key": ghost_user_id,
            "sender": ghost_user_id,
            "content": {"membership": "join"},
        }
    )

    payload = await handler.handle_event(
        {
            "type": "m.room.message",
            "room_id": "!dm:example",
            "sender": "@alice:example",
            "content": {"msgtype": "m.text", "body": "hi"},
        }
    )

    assert payload is not None

