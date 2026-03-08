from __future__ import annotations

import discord

from .publisher import DiscordFeedTransport


class DiscordPyFeedTransport(DiscordFeedTransport):
    def __init__(self, client: discord.Client):
        self._client = client

    async def post_parent_message(self, *, channel_id: str, text: str) -> str:
        channel = await self._get_text_channel(channel_id)
        message = await channel.send(text)
        return str(message.id)

    async def create_thread(
        self,
        *,
        channel_id: str,
        parent_message_id: str,
        name: str,
    ) -> str:
        channel = await self._get_text_channel(channel_id)
        message = await channel.fetch_message(int(parent_message_id))
        thread = await message.create_thread(name=name)
        return str(thread.id)

    async def post_thread_message(self, *, thread_id: str, text: str) -> str:
        thread = await self._get_thread(thread_id)
        message = await thread.send(text)
        return str(message.id)

    async def _get_text_channel(self, channel_id: str) -> discord.TextChannel:
        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise TypeError(f"Channel {channel_id} is not a Discord text channel")
        return channel

    async def _get_thread(self, thread_id: str) -> discord.Thread:
        channel = self._client.get_channel(int(thread_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(thread_id))
        if not isinstance(channel, discord.Thread):
            raise TypeError(f"Channel {thread_id} is not a Discord thread")
        return channel
