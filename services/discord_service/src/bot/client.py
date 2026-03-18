from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import discord
from discord import app_commands

from discord_service.bot.concierge import DMConcierge
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
