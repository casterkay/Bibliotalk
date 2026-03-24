from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import discord
import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent

from discord_service.bot.client import BibliotalkDiscordClient
from discord_service.config import DiscordRuntimeConfig
from discord_service.talks.agent_directory import AgentDirectory
from discord_service.talks.router import FacilitatorRouter
from discord_service.talks.service import TalkService


@dataclass(frozen=True, slots=True)
class _FakeAgentInfo:
    agent_id: uuid.UUID
    agent_slug: str
    display_name: str
    persona_summary: str | None = None


class _FakeAgentDirectory:
    def __init__(self) -> None:
        self._agent = _FakeAgentInfo(
            agent_id=uuid.uuid4(),
            agent_slug="alan-watts",
            display_name="Alan Watts",
        )

    def list_agents(self):
        return [self._agent]

    def resolve_token(self, token: str):
        if token in {"alan-watts", "Alan Watts"}:
            return self._agent
        return None

    def get_by_id(self, agent_id: uuid.UUID):
        if agent_id == self._agent.agent_id:
            return self._agent
        return None

    def resolve_override_prefix(self, _content: str):
        return None


class _FakeTalkService:
    def __init__(self) -> None:
        self.voice_routes = []

    async def start_talk(self, **_kwargs):
        raise NotImplementedError

    async def list_talks(self, **_kwargs):
        return []

    async def handle_thread_message(self, **_kwargs):
        return False

    async def upsert_voice_route(self, **_kwargs):
        return None

    async def list_voice_routes(self, *, guild_id: str):
        _ = guild_id
        return self.voice_routes


class _FakeVoiceProxy:
    def __init__(self) -> None:
        self._rows = []

    async def ensure_bridge(self, **_kwargs):
        raise NotImplementedError

    async def stop_guild(self, **_kwargs):
        return False

    async def status(self, *, guild_id: str | None = None):
        _ = guild_id
        return self._rows

    async def forward_gateway_dispatch(self, **_kwargs):
        return None

    async def stop_all(self, *, reason: str = "shutdown"):
        _ = reason
        return None


class _FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def send_message(self, content: str, **kwargs) -> None:
        self.messages.append((content, kwargs))


class _FakeMember:
    def __init__(self, member_id: int, voice=None) -> None:
        self.id = member_id
        self.voice = voice


class _FakeGuild:
    def __init__(self, guild_id: int, member: _FakeMember) -> None:
        self.id = guild_id
        self._member = member

    def get_member(self, user_id: int):
        if self._member.id == user_id:
            return self._member
        return None


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _FakeInteraction:
    def __init__(self, *, guild, user, channel=None) -> None:
        self.guild = guild
        self.user = user
        self.channel = channel
        self.response = _FakeResponse()


class _NoopOrchestrator:
    async def run(self, _ctx):
        raise NotImplementedError


class _NoopTransport:
    async def list_eligible_guilds(self, *, hub_channel_name: str):
        _ = hub_channel_name
        return []

    async def resolve_hub_channel_id(
        self, *, guild_id: str, hub_channel_name: str
    ) -> str:
        _ = guild_id
        _ = hub_channel_name
        return "hub"

    async def create_private_thread(
        self,
        *,
        hub_channel_id: str,
        name: str,
        auto_archive_duration_minutes: int,
        invitable: bool,
    ) -> str:
        _ = hub_channel_id
        _ = name
        _ = auto_archive_duration_minutes
        _ = invitable
        return "thread"

    async def add_user_to_thread(self, *, thread_id: str, discord_user_id: str) -> None:
        _ = thread_id
        _ = discord_user_id
        return None

    async def send_bot_message(self, *, thread_id: str, content: str) -> str:
        _ = thread_id
        _ = content
        return "message"

    async def pin_message(self, *, thread_id: str, message_id: str) -> None:
        _ = thread_id
        _ = message_id
        return None

    async def thread_exists(self, *, thread_id: str) -> bool:
        _ = thread_id
        return True

    async def send_persona_message(
        self,
        *,
        guild_id: str,
        hub_channel_id: str,
        thread_id: str,
        persona_name: str,
        content: str,
        avatar_url: str | None = None,
    ) -> None:
        _ = guild_id
        _ = hub_channel_id
        _ = thread_id
        _ = persona_name
        _ = content
        _ = avatar_url
        return None


def _build_client() -> BibliotalkDiscordClient:
    config = DiscordRuntimeConfig(
        db_path=Path("/tmp/bibliotalk-test.db"),
        log_level="INFO",
        discord_command_guild_id=None,
        voip_service_url="http://localhost:9012",
        discord_voice_default_text_channel_id=None,
    )
    return BibliotalkDiscordClient(
        config=config,
        talk_service=_FakeTalkService(),
        agent_directory=_FakeAgentDirectory(),
        voice_gateway_proxy=_FakeVoiceProxy(),
        intents=discord.Intents.none(),
    )


@pytest.mark.anyio
async def test_voice_join_requires_user_in_voice_channel() -> None:
    client = _build_client()
    interaction = _FakeInteraction(
        guild=_FakeGuild(guild_id=1, member=_FakeMember(member_id=11, voice=None)),
        user=_FakeUser(11),
    )

    await client._cmd_voice_join(interaction, agent=None, text_channel=None)

    assert interaction.response.messages
    assert "Join a voice channel first." in interaction.response.messages[0][0]
    await client.close()


@pytest.mark.anyio
async def test_voice_status_reports_active_bridge() -> None:
    client = _build_client()
    assert client.voice_gateway_proxy is not None
    client.voice_gateway_proxy._rows = [
        {
            "bridge_id": "discord:1:2:3",
            "agent_id": "3",
            "voice_channel_id": "2",
            "guild_id": "1",
            "text_channel_id": None,
            "text_thread_id": None,
        }
    ]
    interaction = _FakeInteraction(
        guild=_FakeGuild(guild_id=1, member=_FakeMember(member_id=11, voice=None)),
        user=_FakeUser(11),
    )

    await client._cmd_voice_status(interaction)

    assert interaction.response.messages
    content = interaction.response.messages[0][0]
    assert "discord:1:2:3" in content
    assert "<#2>" in content
    await client.close()


@pytest.mark.anyio
async def test_voice_status_reports_saved_binding_without_active_bridge() -> None:
    client = _build_client()
    fake_talk_service = client.talk_service
    assert isinstance(fake_talk_service, _FakeTalkService)
    fake_talk_service.voice_routes = [
        type(
            "VoiceRoute",
            (),
            {
                "agent_id": client.agent_directory.list_agents()[0].agent_id,
                "voice_channel_id": "456",
                "text_channel_id": "789",
                "text_thread_id": None,
            },
        )()
    ]
    interaction = _FakeInteraction(
        guild=_FakeGuild(guild_id=1, member=_FakeMember(member_id=11, voice=None)),
        user=_FakeUser(11),
    )

    await client._cmd_voice_status(interaction)

    assert interaction.response.messages
    content = interaction.response.messages[0][0]
    assert "Saved voice bindings:" in content
    assert "<#456>" in content
    assert "<#789>" in content
    await client.close()


@pytest.mark.anyio
async def test_talk_service_voice_routes_are_scoped_by_agent_and_guild(
    tmp_path,
) -> None:
    db = tmp_path / "voice-routes.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    agent_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=agent_id,
                slug="alan-watts",
                display_name="Alan Watts",
                kind="figure",
                persona_summary=None,
                is_active=True,
            )
        )
        await session.commit()

    directory = AgentDirectory(session_factory=session_factory)
    await directory.refresh()
    service = TalkService(
        session_factory=session_factory,
        agent_directory=directory,
        router=FacilitatorRouter(),
        orchestrator=_NoopOrchestrator(),
        transport=_NoopTransport(),
        hub_channel_name="bibliotalk",
    )

    await service.upsert_voice_route(
        guild_id="guild-1",
        agent_id=agent_id,
        voice_channel_id="voice-a",
        text_channel_id="text-a",
        text_thread_id=None,
        updated_by_user_id="user-1",
    )
    await service.upsert_voice_route(
        guild_id="guild-1",
        agent_id=agent_id,
        voice_channel_id="voice-b",
        text_channel_id="text-b",
        text_thread_id="thread-b",
        updated_by_user_id="user-2",
    )
    await service.upsert_voice_route(
        guild_id="guild-2",
        agent_id=agent_id,
        voice_channel_id="voice-c",
        text_channel_id=None,
        text_thread_id=None,
        updated_by_user_id="user-3",
    )

    guild_one = await service.list_voice_routes(guild_id="guild-1")
    guild_two = await service.list_voice_routes(guild_id="guild-2")

    assert len(guild_one) == 1
    assert guild_one[0].voice_channel_id == "voice-b"
    assert guild_one[0].text_channel_id == "text-b"
    assert guild_one[0].text_thread_id == "thread-b"
    assert guild_one[0].updated_by_user_id == "user-2"
    assert len(guild_two) == 1
    assert guild_two[0].voice_channel_id == "voice-c"
