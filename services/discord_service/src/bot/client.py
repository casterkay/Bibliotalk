from __future__ import annotations

import logging
import json
import os
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import discord
from discord import app_commands

from discord_service.bot.concierge import DMConcierge
from discord_service.bot.voice_gateway_proxy import DiscordVoiceGatewayProxy
from discord_service.config import DiscordRuntimeConfig
from discord_service.talks.agent_directory import AgentDirectory
from discord_service.talks.service import TalkService
from discord_service.talks.transport import EligibleGuild

logger = logging.getLogger("discord_service")


@dataclass(frozen=True, slots=True)
class _TalkCommandContext:
    characters: str


class _GuildPickerView(discord.ui.View):
    def __init__(
        self,
        *,
        eligible_guilds: list[EligibleGuild],
        talk_service: TalkService,
        owner_discord_user_id: str,
        context: _TalkCommandContext,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._talk_service = talk_service
        self._owner_discord_user_id = owner_discord_user_id
        self._context = context

        options = [
            discord.SelectOption(label=item.name[:100], value=item.guild_id)
            for item in eligible_guilds[:25]
        ]
        self._select = discord.ui.Select(
            placeholder="Choose a server",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._select.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        guild_id = (self._select.values[0] if self._select.values else "").strip()
        if not guild_id:
            await interaction.response.send_message(
                "No server selected.", ephemeral=True
            )
            return

        result = await self._talk_service.start_talk(
            owner_discord_user_id=self._owner_discord_user_id,
            characters=self._context.characters,
            guild_id=guild_id,
        )
        if result.kind in {"created", "resumed"} and result.thread_url():
            await interaction.response.send_message(
                f"{result.message}\n{result.thread_url()}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self.stop()
            return

        await interaction.response.send_message(
            result.message[:2000], allowed_mentions=discord.AllowedMentions.none()
        )


class BibliotalkDiscordClient(discord.Client):
    def __init__(
        self,
        *,
        config: DiscordRuntimeConfig,
        talk_service: TalkService,
        agent_directory: AgentDirectory,
        dm_concierge: DMConcierge | None = None,
        voice_gateway_proxy: DiscordVoiceGatewayProxy | None = None,
        on_ready_callback: Any | None = None,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        proxy = kwargs.pop("proxy", None)
        if proxy is None:
            proxy = (
                os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or ""
            ).strip() or None
        super().__init__(proxy=proxy, **kwargs)
        self.config = config
        self.talk_service = talk_service
        self.agent_directory = agent_directory
        self.dm_concierge = dm_concierge
        self.voice_gateway_proxy = voice_gateway_proxy
        self.on_ready_callback = on_ready_callback
        self.logger = logger or logging.getLogger("discord_service")
        self.tree = app_commands.CommandTree(self)
        self._ready_callback_ran = False
        self._synced = False

        self.tree.add_command(
            app_commands.Command(
                name="talk",
                description="Start a private talk thread (DM only).",
                callback=self._cmd_talk,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="talks",
                description="List your recent talks (DM only).",
                callback=self._cmd_talks,
            )
        )
        voice_group = app_commands.Group(
            name="voice",
            description="Manage Bibliotalk voice sessions in this server.",
        )
        voice_group.add_command(
            app_commands.Command(
                name="join",
                description="Join your current voice channel.",
                callback=self._cmd_voice_join,
            )
        )
        voice_group.add_command(
            app_commands.Command(
                name="leave",
                description="Leave the active voice session in this server.",
                callback=self._cmd_voice_leave,
            )
        )
        voice_group.add_command(
            app_commands.Command(
                name="status",
                description="Show voice bridge status for this server.",
                callback=self._cmd_voice_status,
            )
        )
        self.tree.add_command(voice_group)

    async def setup_hook(self) -> None:
        if self._synced:
            return
        guild_id = self.config.discord_command_guild_id
        if guild_id:
            await self.tree.sync(guild=discord.Object(id=int(guild_id)))
        else:
            await self.tree.sync()
        self._synced = True

    async def on_ready(self) -> None:
        self.logger.info("discord client ready user=%s", self.user)
        if self.on_ready_callback is not None and not self._ready_callback_ran:
            self._ready_callback_ran = True
            await self.on_ready_callback()

    async def close(self) -> None:
        if self.voice_gateway_proxy is not None:
            try:
                await self.voice_gateway_proxy.stop_all(reason="discord_client_close")
            except Exception:
                self.logger.exception("voice gateway proxy stop_all failed")
        await super().close()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            if self.dm_concierge is None:
                return
            await self.dm_concierge.handle(
                channel=message.channel,
                author=message.author,
                content=message.content,
            )
            return

        if message.guild is None or not isinstance(message.channel, discord.Thread):
            return

        handled = await self.talk_service.handle_thread_message(
            guild_id=str(message.guild.id),
            thread_id=str(message.channel.id),
            author_discord_user_id=str(message.author.id),
            content=message.content,
        )
        if handled:
            self.logger.info(
                "talk message handled guild_id=%s thread_id=%s user_id=%s",
                message.guild.id,
                message.channel.id,
                message.author.id,
            )

    async def on_socket_raw_receive(self, msg: str) -> None:
        if self.voice_gateway_proxy is None:
            return
        try:
            payload = json.loads(msg)
        except Exception:
            return
        if payload.get("op") != 0:
            return
        event_type = str(payload.get("t") or "")
        if event_type not in {"VOICE_STATE_UPDATE", "VOICE_SERVER_UPDATE"}:
            return
        data = payload.get("d")
        if not isinstance(data, dict):
            return
        await self.voice_gateway_proxy.forward_gateway_dispatch(
            event_type=event_type,
            data=data,
        )

    async def _cmd_talk(
        self, interaction: discord.Interaction, characters: str
    ) -> None:
        if interaction.guild is not None:
            await interaction.response.send_message(
                "DM me and run `/talk ...` there.",
                ephemeral=True,
            )
            return

        owner_id = str(interaction.user.id)
        result = await self.talk_service.start_talk(
            owner_discord_user_id=owner_id,
            characters=characters,
            guild_id=None,
        )
        if result.kind == "choose_guild" and result.eligible_guilds:
            view = _GuildPickerView(
                eligible_guilds=result.eligible_guilds,
                talk_service=self.talk_service,
                owner_discord_user_id=owner_id,
                context=_TalkCommandContext(characters=characters),
            )
            await interaction.response.send_message(
                result.message[:2000],
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        if result.thread_url():
            await interaction.response.send_message(
                f"{result.message}\n{result.thread_url()}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await interaction.response.send_message(
            result.message[:2000], allowed_mentions=discord.AllowedMentions.none()
        )

    async def _cmd_talks(self, interaction: discord.Interaction) -> None:
        if interaction.guild is not None:
            await interaction.response.send_message(
                "DM me and run `/talks` there.",
                ephemeral=True,
            )
            return

        entries = await self.talk_service.list_talks(
            owner_discord_user_id=str(interaction.user.id),
            limit=10,
        )
        if not entries:
            await interaction.response.send_message(
                "No talks yet. Start one with `/talk Alan Watts`.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        lines: list[str] = []
        for entry in entries:
            title = " + ".join(entry.participant_names)
            ago = entry.last_activity_at.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")
            lines.append(f"- {title}: {entry.thread_url()} (last: {ago})")

        await interaction.response.send_message(
            "\n".join(lines)[:2000],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _cmd_voice_join(
        self,
        interaction: discord.Interaction,
        agent: str | None = None,
        text_channel: discord.TextChannel | None = None,
    ) -> None:
        if self.voice_gateway_proxy is None:
            await interaction.response.send_message(
                "Voice bridge is not configured.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                "Run this command in a server.",
                ephemeral=True,
            )
            return

        member = (
            interaction.user if isinstance(interaction.user, discord.Member) else None
        )
        if member is None:
            member = interaction.guild.get_member(interaction.user.id)
        voice_state = member.voice if member is not None else None
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "Join a voice channel first.",
                ephemeral=True,
            )
            return
        if not isinstance(
            voice_state.channel, (discord.VoiceChannel, discord.StageChannel)
        ):
            await interaction.response.send_message(
                "Your current channel is not a supported voice channel.",
                ephemeral=True,
            )
            return

        chosen_agent = self._resolve_voice_agent(agent)
        if chosen_agent is None:
            available = ", ".join(
                sorted({a.agent_slug for a in self.agent_directory.list_agents()})
            )
            await interaction.response.send_message(
                f"Unknown agent. Available: {available or '(none)'}",
                ephemeral=True,
            )
            return

        destination_channel_id = (
            str(text_channel.id)
            if text_channel is not None
            else self._resolve_voice_text_channel_id(interaction)
        )

        await interaction.response.defer(thinking=True)
        bridge = await self.voice_gateway_proxy.ensure_bridge(
            guild_id=str(interaction.guild.id),
            voice_channel_id=str(voice_state.channel.id),
            agent_id=str(chosen_agent.agent_id),
            initiator_user_id=str(interaction.user.id),
            text_channel_id=destination_channel_id or None,
            text_thread_id=(
                str(interaction.channel.id)
                if isinstance(interaction.channel, discord.Thread)
                else None
            ),
        )
        await self.talk_service.upsert_voice_route(
            guild_id=str(interaction.guild.id),
            agent_id=chosen_agent.agent_id,
            voice_channel_id=str(voice_state.channel.id),
            text_channel_id=destination_channel_id or None,
            text_thread_id=(
                str(interaction.channel.id)
                if isinstance(interaction.channel, discord.Thread)
                else None
            ),
            updated_by_user_id=str(interaction.user.id),
        )
        await interaction.followup.send(
            (
                f"Voice session started.\n"
                f"- Agent: `{chosen_agent.agent_slug}`\n"
                f"- Voice channel: <#{voice_state.channel.id}>\n"
                f"- Bridge: `{bridge.bridge_id}`"
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _cmd_voice_leave(self, interaction: discord.Interaction) -> None:
        if self.voice_gateway_proxy is None:
            await interaction.response.send_message(
                "Voice bridge is not configured.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                "Run this command in a server.",
                ephemeral=True,
            )
            return
        guild_id = str(interaction.guild.id)
        saved_routes = await self.talk_service.list_voice_routes(guild_id=guild_id)

        stopped = await self.voice_gateway_proxy.stop_guild(
            guild_id=guild_id, reason="user_requested_leave"
        )
        if stopped:
            if saved_routes:
                await interaction.response.send_message(
                    "Voice session stopped. Saved voice preference was kept for this server."
                )
            else:
                await interaction.response.send_message("Voice session stopped.")
            return
        if saved_routes:
            await interaction.response.send_message(
                "No active voice session for this server. Saved voice preference is still available."
            )
            return
        await interaction.response.send_message(
            "No active voice session for this server."
        )

    async def _cmd_voice_status(self, interaction: discord.Interaction) -> None:
        if self.voice_gateway_proxy is None:
            await interaction.response.send_message(
                "Voice bridge is not configured.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                "Run this command in a server.",
                ephemeral=True,
            )
            return
        guild_id = str(interaction.guild.id)
        active_rows = await self.voice_gateway_proxy.status(guild_id=guild_id)
        saved_routes = await self.talk_service.list_voice_routes(guild_id=guild_id)
        if not active_rows and not saved_routes:
            await interaction.response.send_message(
                "No active or saved voice session in this server."
            )
            return
        lines: list[str] = []
        if active_rows:
            row = active_rows[0]
            lines.append("Active voice session:")
            lines.append(f"- Bridge: `{row['bridge_id']}`")
            lines.append(f"- Agent: `{row['agent_id']}`")
            lines.append(f"- Voice channel: <#{row['voice_channel_id']}>")
            if row.get("text_thread_id"):
                lines.append(f"- Transcript thread: <#{row['text_thread_id']}>")
            elif row.get("text_channel_id"):
                lines.append(f"- Transcript channel: <#{row['text_channel_id']}>")
        if saved_routes:
            lines.append("Saved voice bindings:")
            for route in saved_routes[:8]:
                agent_name = str(route.agent_id)
                if route.agent_id is not None:
                    info = self.agent_directory.get_by_id(route.agent_id)
                    if info is not None:
                        agent_name = info.agent_slug
                voice_display = (
                    f"<#{route.voice_channel_id}>"
                    if route.voice_channel_id
                    else "(unset)"
                )
                text_display = (
                    f"<#{route.text_thread_id}>"
                    if route.text_thread_id
                    else (
                        f"<#{route.text_channel_id}>"
                        if route.text_channel_id
                        else "(unset)"
                    )
                )
                lines.append(
                    f"- `{agent_name}` voice={voice_display} transcripts={text_display}"
                )

        await interaction.response.send_message(
            "\n".join(lines)[:2000], allowed_mentions=discord.AllowedMentions.none()
        )

    def _resolve_voice_agent(self, token: str | None):
        candidate = (token or "").strip()
        if candidate:
            return self.agent_directory.resolve_token(candidate)
        agents = self.agent_directory.list_agents()
        if not agents:
            return None
        return sorted(agents, key=lambda item: item.display_name.lower())[0]

    def _resolve_voice_text_channel_id(
        self, interaction: discord.Interaction
    ) -> str | None:
        if isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            return str(interaction.channel.id)
        return self.config.discord_voice_default_text_channel_id
