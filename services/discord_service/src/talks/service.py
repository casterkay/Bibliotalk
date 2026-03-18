from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from agents_service.agent.orchestrator import DMContext, DMOrchestrator
from agents_service.models.citation import (
    NO_EVIDENCE_RESPONSE,
    extract_memory_links,
    validate_evidence_links,
)
from bt_store.models_core import Agent, Room, RoomMember
from bt_store.models_runtime import PlatformUserSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .agent_directory import AgentDirectory, AgentInfo
from .router import FacilitatorRouter
from .transport import EligibleGuild, TalkTransport

logger = logging.getLogger("discord_service")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class TalkStartResult:
    kind: str  # created|resumed|choose_guild|error
    message: str
    talk_id: uuid.UUID | None = None
    guild_id: str | None = None
    thread_id: str | None = None
    participant_slugs: list[str] | None = None
    eligible_guilds: list[EligibleGuild] | None = None

    def thread_url(self) -> str | None:
        if not self.guild_id or not self.thread_id:
            return None
        return f"https://discord.com/channels/{self.guild_id}/{self.thread_id}"


@dataclass(frozen=True, slots=True)
class TalkListEntry:
    talk_id: uuid.UUID
    guild_id: str
    thread_id: str
    status: str
    participant_slugs: list[str]
    participant_names: list[str]
    last_activity_at: datetime

    def thread_url(self) -> str:
        return f"https://discord.com/channels/{self.guild_id}/{self.thread_id}"


class TalkService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        agent_directory: AgentDirectory,
        router: FacilitatorRouter,
        orchestrator: DMOrchestrator,
        transport: TalkTransport,
        hub_channel_name: str,
        logger_: logging.Logger | None = None,
        max_participants: int = 6,
    ) -> None:
        self._session_factory = session_factory
        self._directory = agent_directory
        self._router = router
        self._orchestrator = orchestrator
        self._transport = transport
        self._hub_channel_name = hub_channel_name
        self._logger = logger_ or logger
        self._max_participants = max(1, max_participants)
        self._thread_locks: dict[str, asyncio.Lock] = {}

    async def start_talk(
        self,
        *,
        owner_discord_user_id: str,
        characters: str,
        guild_id: str | None = None,
    ) -> TalkStartResult:
        participants = self._parse_participants(characters)
        if not participants:
            return TalkStartResult(
                kind="error",
                message="No characters specified. Try `/talk Alan Watts, Naval`.",
            )
        if len(participants) > self._max_participants:
            return TalkStartResult(
                kind="error",
                message=f"Too many characters. Max is {self._max_participants}.",
            )

        resolved: list[AgentInfo] = []
        for token in participants:
            info = self._directory.resolve_token(token)
            if info is None:
                available = ", ".join(
                    sorted({a.display_name for a in self._directory.list_agents()})
                )
                return TalkStartResult(
                    kind="error",
                    message=f"Unknown character: `{token}`. Available: {available}",
                )
            if info.agent_id not in {item.agent_id for item in resolved}:
                resolved.append(info)

        chosen_guild = await self._resolve_guild_id(
            owner_discord_user_id=owner_discord_user_id,
            explicit_guild_id=guild_id,
        )
        if isinstance(chosen_guild, list):
            if len(chosen_guild) == 1:
                chosen_guild_id = chosen_guild[0].guild_id
            else:
                return TalkStartResult(
                    kind="choose_guild",
                    message="Choose which server should host this talk:",
                    eligible_guilds=chosen_guild,
                    participant_slugs=[a.agent_slug for a in resolved],
                )
        else:
            chosen_guild_id = chosen_guild

        try:
            hub_channel_id = await self._transport.resolve_hub_channel_id(
                guild_id=chosen_guild_id,
                hub_channel_name=self._hub_channel_name,
            )
        except Exception as exc:
            self._logger.info(
                "hub channel resolution failed guild_id=%s err=%s",
                chosen_guild_id,
                type(exc).__name__,
            )
            # Default guild might be stale; force re-pick.
            guilds = await self._transport.list_eligible_guilds(
                hub_channel_name=self._hub_channel_name
            )
            if not guilds:
                return TalkStartResult(
                    kind="error",
                    message=(
                        "I couldn't find any server with a `#bibliotalk` channel where I can create private threads."
                    ),
                    participant_slugs=[a.agent_slug for a in resolved],
                )
            return TalkStartResult(
                kind="choose_guild",
                message="Choose which server should host this talk:",
                eligible_guilds=guilds,
                participant_slugs=[a.agent_slug for a in resolved],
            )

        async with self._session_factory() as session:
            existing = await self._find_existing_open_talk(
                session,
                owner_discord_user_id=owner_discord_user_id,
                guild_id=chosen_guild_id,
                participant_ids={p.agent_id for p in resolved},
            )
            if existing is not None:
                if await self._transport.thread_exists(thread_id=existing.room_id):
                    existing.last_activity_at = _utc_now()
                    await session.commit()
                    await self._upsert_user_default_guild(
                        session,
                        owner_discord_user_id=owner_discord_user_id,
                        guild_id=chosen_guild_id,
                    )
                    await session.commit()
                    try:
                        await self._transport.add_user_to_thread(
                            thread_id=existing.room_id,
                            discord_user_id=owner_discord_user_id,
                        )
                    except Exception:
                        pass
                    return TalkStartResult(
                        kind="resumed",
                        message="Resumed your existing talk.",
                        talk_id=existing.room_pk,
                        guild_id=chosen_guild_id,
                        thread_id=existing.room_id,
                        participant_slugs=[a.agent_slug for a in resolved],
                    )

                existing.status = "closed"
                await session.commit()

        thread_name = self._build_thread_name(resolved)
        thread_id = await self._transport.create_private_thread(
            hub_channel_id=hub_channel_id,
            name=thread_name,
            auto_archive_duration_minutes=10080,  # 7 days
            invitable=False,
        )
        await self._transport.add_user_to_thread(
            thread_id=thread_id,
            discord_user_id=owner_discord_user_id,
        )

        roster_message_id = await self._transport.send_bot_message(
            thread_id=thread_id,
            content=self._build_roster_message(resolved),
        )
        try:
            await self._transport.pin_message(
                thread_id=thread_id, message_id=roster_message_id
            )
        except Exception:
            pass

        talk_id = uuid.uuid4()
        async with self._session_factory() as session:
            room = Room(
                room_pk=talk_id,
                platform="discord",
                room_id=thread_id,
                kind="dialogue",
                status="open",
                last_activity_at=_utc_now(),
                meta_json={
                    "guild_id": chosen_guild_id,
                    "hub_channel_id": hub_channel_id,
                },
                created_at=_utc_now(),
            )
            session.add(room)
            session.add(
                RoomMember(
                    room_pk=room.room_pk,
                    platform="discord",
                    platform_user_id=owner_discord_user_id,
                    agent_id=None,
                    member_kind="human",
                    role="owner",
                    display_order=0,
                    created_at=_utc_now(),
                )
            )
            for idx, info in enumerate(resolved):
                session.add(
                    RoomMember(
                        room_pk=room.room_pk,
                        platform="discord",
                        platform_user_id=f"agent:{info.agent_slug}",
                        agent_id=info.agent_id,
                        member_kind="agent",
                        role="participant",
                        display_order=idx,
                        created_at=_utc_now(),
                    )
                )
            await self._upsert_user_default_guild(
                session,
                owner_discord_user_id=owner_discord_user_id,
                guild_id=chosen_guild_id,
            )
            await session.commit()

        return TalkStartResult(
            kind="created",
            message="Created a new talk thread.",
            talk_id=talk_id,
            guild_id=chosen_guild_id,
            thread_id=thread_id,
            participant_slugs=[a.agent_slug for a in resolved],
        )

    async def list_talks(
        self, *, owner_discord_user_id: str, limit: int = 10
    ) -> list[TalkListEntry]:
        max_rows = max(1, limit)
        async with self._session_factory() as session:
            rooms = (
                (
                    await session.execute(
                        select(Room)
                        .join(RoomMember, RoomMember.room_pk == Room.room_pk)
                        .where(
                            Room.platform == "discord",
                            Room.kind == "dialogue",
                            RoomMember.platform == "discord",
                            RoomMember.platform_user_id == owner_discord_user_id,
                            RoomMember.role == "owner",
                        )
                        .order_by(Room.last_activity_at.desc())
                        .limit(max_rows)
                    )
                )
                .scalars()
                .all()
            )

            entries: list[TalkListEntry] = []
            for room in rooms:
                meta = dict(room.meta_json or {})
                guild = str(meta.get("guild_id") or "")
                participants = (
                    await session.execute(
                        select(Agent, RoomMember)
                        .join(RoomMember, RoomMember.agent_id == Agent.agent_id)
                        .where(RoomMember.room_pk == room.room_pk)
                        .order_by(RoomMember.display_order)
                    )
                ).all()
                entries.append(
                    TalkListEntry(
                        talk_id=room.room_pk,
                        guild_id=guild,
                        thread_id=room.room_id,
                        status=room.status,
                        participant_slugs=[agent.slug for agent, _ in participants],
                        participant_names=[
                            agent.display_name for agent, _ in participants
                        ],
                        last_activity_at=room.last_activity_at,
                    )
                )

        return entries

    async def handle_thread_message(
        self,
        *,
        guild_id: str,
        thread_id: str,
        author_discord_user_id: str,
        content: str,
    ) -> bool:
        room = await self._get_open_talk_by_thread_id(thread_id)
        if room is None:
            return False

        lock = self._thread_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            room = await self._get_open_talk_by_thread_id(thread_id)
            if room is None:
                return False

            participants = await self._get_talk_participants(room.room_pk)
            if not participants:
                await self._transport.send_bot_message(
                    thread_id=thread_id,
                    content="This talk has no participants configured.",
                )
                return True

            override_token = self._directory.resolve_override_prefix(content)
            speaker_infos: list[AgentInfo] = []
            effective_content = content
            if override_token:
                override_info = self._directory.resolve_token(override_token)
                if override_info and override_info.agent_id in {
                    p.agent_id for p in participants
                }:
                    speaker_infos = [override_info]
                    effective_content = content.lstrip()[
                        len(override_token) + 1 :
                    ].lstrip()
                    if not effective_content:
                        effective_content = content

            last_slug = None
            last_routed_id = None
            try:
                raw = (room.meta_json or {}).get("last_routed_agent_id")
                if isinstance(raw, str) and raw:
                    last_routed_id = uuid.UUID(raw)
            except Exception:
                last_routed_id = None
            if last_routed_id:
                last_info = self._directory.get_by_id(last_routed_id)
                last_slug = last_info.agent_slug if last_info else None

            if not speaker_infos:
                decision = await self._router.route(
                    message=content,
                    participants=participants,
                    last_speaker_slug=last_slug,
                )
                if decision is not None:
                    speaker_infos = [
                        info
                        for info in participants
                        if info.agent_slug in set(decision.speaker_slugs)
                    ]
                    if decision.facilitator_note:
                        await self._transport.send_bot_message(
                            thread_id=thread_id, content=decision.facilitator_note
                        )

            if not speaker_infos:
                speaker_infos = [self._pick_next_speaker(participants, last_slug)]

            for speaker in speaker_infos:
                await self._respond_as_character(
                    guild_id=guild_id,
                    hub_channel_id=str(
                        (room.meta_json or {}).get("hub_channel_id") or ""
                    ),
                    thread_id=thread_id,
                    author_discord_user_id=author_discord_user_id,
                    speaker=speaker,
                    content=effective_content,
                )

            async with self._session_factory() as session:
                refreshed = await session.get(Room, room.room_pk)
                if refreshed is not None:
                    refreshed.last_activity_at = _utc_now()
                    meta = dict(refreshed.meta_json or {})
                    meta["last_routed_agent_id"] = str(speaker_infos[-1].agent_id)
                    refreshed.meta_json = meta
                await session.commit()

        return True

    def _parse_participants(self, characters: str) -> list[str]:
        raw = (characters or "").strip()
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]

    async def _resolve_guild_id(
        self, *, owner_discord_user_id: str, explicit_guild_id: str | None
    ) -> str | list[EligibleGuild]:
        if explicit_guild_id:
            return explicit_guild_id

        async with self._session_factory() as session:
            settings = await session.get(
                PlatformUserSettings,
                {"platform": "discord", "platform_user_id": owner_discord_user_id},
            )
            config = dict(settings.config_json or {}) if settings else {}
            default_guild = (config.get("default_guild_id") if config else None) or None

        if default_guild:
            return default_guild

        return await self._transport.list_eligible_guilds(
            hub_channel_name=self._hub_channel_name
        )

    async def _upsert_user_default_guild(
        self, session: AsyncSession, *, owner_discord_user_id: str, guild_id: str
    ) -> None:
        settings = await session.get(
            PlatformUserSettings,
            {"platform": "discord", "platform_user_id": owner_discord_user_id},
        )
        if settings is None:
            session.add(
                PlatformUserSettings(
                    platform="discord",
                    platform_user_id=owner_discord_user_id,
                    config_json={"default_guild_id": guild_id},
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
            )
            return
        config = dict(settings.config_json or {})
        config["default_guild_id"] = guild_id
        settings.config_json = config
        settings.updated_at = _utc_now()

    async def _find_existing_open_talk(
        self,
        session: AsyncSession,
        *,
        owner_discord_user_id: str,
        guild_id: str,
        participant_ids: set[uuid.UUID],
    ) -> Room | None:
        rooms = (
            (
                await session.execute(
                    select(Room)
                    .join(RoomMember, RoomMember.room_pk == Room.room_pk)
                    .where(
                        Room.platform == "discord",
                        Room.kind == "dialogue",
                        Room.status == "open",
                        RoomMember.platform == "discord",
                        RoomMember.platform_user_id == owner_discord_user_id,
                        RoomMember.role == "owner",
                    )
                    .order_by(Room.last_activity_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for room in rooms:
            meta = dict(room.meta_json or {})
            if str(meta.get("guild_id") or "") != guild_id:
                continue
            ids = (
                (
                    await session.execute(
                        select(RoomMember.agent_id).where(
                            RoomMember.room_pk == room.room_pk,
                            RoomMember.agent_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if set([i for i in ids if i is not None]) == participant_ids:
                return room
        return None

    async def _get_open_talk_by_thread_id(self, thread_id: str) -> Room | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(Room).where(
                        Room.platform == "discord",
                        Room.room_id == thread_id,
                        Room.kind == "dialogue",
                        Room.status == "open",
                    )
                )
            ).scalar_one_or_none()

    async def _get_talk_participants(self, talk_id: uuid.UUID) -> list[AgentInfo]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Agent, RoomMember)
                    .join(RoomMember, RoomMember.agent_id == Agent.agent_id)
                    .where(RoomMember.room_pk == talk_id)
                    .order_by(RoomMember.display_order)
                )
            ).all()
        infos: list[AgentInfo] = []
        for agent, _participant in rows:
            info = self._directory.get_by_id(agent.agent_id)
            if info is None:
                info = AgentInfo(
                    agent_id=agent.agent_id,
                    agent_slug=agent.slug,
                    display_name=agent.display_name,
                    persona_summary=agent.persona_summary,
                )
            infos.append(info)
        return infos

    def _pick_next_speaker(
        self, participants: list[AgentInfo], last_slug: str | None
    ) -> AgentInfo:
        if not participants:
            raise ValueError("participants cannot be empty")
        if not last_slug:
            return participants[0]
        for idx, info in enumerate(participants):
            if info.agent_slug == last_slug:
                return participants[(idx + 1) % len(participants)]
        return participants[0]

    async def _respond_as_character(
        self,
        *,
        guild_id: str,
        hub_channel_id: str,
        thread_id: str,
        author_discord_user_id: str,
        speaker: AgentInfo,
        content: str,
    ) -> None:
        result = await self._orchestrator.run(
            DMContext(
                agent_id=speaker.agent_id,
                agent_slug=speaker.agent_slug,
                discord_user_id=author_discord_user_id,
                discord_channel_id=thread_id,
                content=content,
            )
        )
        validated_text = validate_evidence_links(
            result.response_text,
            list(result.evidence),
            agent_emos_user_id=speaker.agent_slug,
        )
        if not extract_memory_links(validated_text):
            validated_text = NO_EVIDENCE_RESPONSE

        for chunk in _split_response_text(validated_text):
            await self._transport.send_persona_message(
                guild_id=guild_id,
                hub_channel_id=hub_channel_id,
                thread_id=thread_id,
                persona_name=speaker.display_name,
                content=chunk,
            )

    def _build_thread_name(self, participants: list[AgentInfo]) -> str:
        date = _utc_now().strftime("%Y-%m-%d")
        names = " + ".join(p.display_name for p in participants[:3])
        if len(participants) > 3:
            names = f"{names} +{len(participants) - 3}"
        return f"talk: {names} — {date}"[:100]

    def _build_roster_message(self, participants: list[AgentInfo]) -> str:
        roster = "\n".join(
            f"- {p.display_name} (`@{p.agent_slug}`)" for p in participants
        )
        return (
            "Welcome to your private Bibliotalk thread.\n\n"
            "**Participants**\n"
            f"{roster}\n\n"
            "**How it works**\n"
            "- Just send messages normally.\n"
            "- I route each message to the most relevant character(s).\n"
            "- Override routing by starting a message with `@slug` (e.g. `@alan-watts ...`).\n"
        ).strip()[:2000]


def _split_response_text(text: str, *, limit: int = 2000) -> list[str]:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return [compact]
    sentences = _SENTENCE_SPLIT_RE.split(compact)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        merged = f"{current} {candidate}".strip()
        if current and len(merged) > limit:
            chunks.append(current)
            current = candidate
            continue
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = candidate[:limit]
            continue
        current = merged
    if current:
        chunks.append(current)
    return chunks or [compact[:limit]]
