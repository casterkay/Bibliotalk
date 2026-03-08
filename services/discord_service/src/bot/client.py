from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import discord

from .dm_handler import DMHandler
from .message_models import InboundDM


class FigureDiscordClient(discord.Client):
    def __init__(
        self,
        *,
        figure_id: UUID,
        dm_handler: DMHandler,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.figure_id = figure_id
        self.dm_handler = dm_handler
        self.logger = logger or logging.getLogger("discord_service")

    async def on_ready(self) -> None:
        self.logger.info("discord client ready user=%s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        responses = await self.dm_handler.handle(
            InboundDM(
                discord_message_id=str(message.id),
                discord_user_id=str(message.author.id),
                discord_channel_id=str(message.channel.id),
                figure_id=self.figure_id,
                content=message.content,
                received_at=datetime.now(tz=UTC),
            )
        )
        for response in responses:
            await message.channel.send(response.response_text)
