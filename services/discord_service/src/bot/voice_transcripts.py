from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Awaitable, Callable

import discord

logger = logging.getLogger("discord_service")


def _compact_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _trim(value: str | None) -> str:
    return (value or "").strip()


@dataclass(slots=True)
class _RollingTranscriptState:
    channel: Any
    bridge_id: str
    kind: str
    message: discord.Message | None = None
    message_text: str = ""
    pending_parts: list[str] = field(default_factory=list)
    last_activity_at: float = 0.0
    last_emit_at: float = 0.0
    flush_task: asyncio.Task[None] | None = None


class VoiceTranscriptPublisher:
    def __init__(
        self,
        *,
        client: discord.Client,
        default_text_channel_id: str | None = None,
        logger_: logging.Logger | None = None,
        debounce_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._default_text_channel_id = (default_text_channel_id or "").strip() or None
        self._logger = logger_ or logger
        self._debounce_seconds = max(0.01, debounce_seconds)
        self._sleep = sleep
        self._clock = clock or monotonic
        self._recent_dedup: deque[tuple[str, str, str]] = deque(maxlen=128)
        self._streams: dict[tuple[str, str, str], _RollingTranscriptState] = {}
        self._lock = asyncio.Lock()

    async def publish_input(self, payload: dict[str, Any]) -> None:
        await self._publish(kind="input", payload=payload)

    async def publish_output(self, payload: dict[str, Any]) -> None:
        await self._publish(kind="output", payload=payload)

    async def close(self) -> None:
        async with self._lock:
            tasks = [
                stream.flush_task
                for stream in self._streams.values()
                if stream.flush_task is not None and not stream.flush_task.done()
            ]
            self._streams.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _publish(self, *, kind: str, payload: dict[str, Any]) -> None:
        text = _compact_text(str(payload.get("text") or ""))
        if not text:
            return

        bridge_id = _trim(str(payload.get("bridge_id") or ""))
        dedup_key = (bridge_id, kind, text)
        if dedup_key in self._recent_dedup:
            return
        self._recent_dedup.append(dedup_key)

        channel_id = _trim(
            str(payload.get("text_thread_id") or payload.get("text_channel_id") or "")
        )
        if not channel_id:
            channel_id = self._default_text_channel_id or ""
        if not channel_id:
            return

        channel = await self._resolve_channel(
            channel_id=channel_id, bridge_id=bridge_id, kind=kind
        )
        if channel is None:
            return

        key = (bridge_id, kind, channel_id)
        now = self._clock()
        async with self._lock:
            stream = self._streams.get(key)
            if stream is None:
                stream = _RollingTranscriptState(
                    channel=channel,
                    bridge_id=bridge_id,
                    kind=kind,
                )
                self._streams[key] = stream
            else:
                stream.channel = channel
                if (
                    stream.last_emit_at > 0
                    and (now - stream.last_emit_at) > self._debounce_seconds
                ):
                    stream.message = None
                    stream.message_text = ""

            stream.pending_parts.append(text)
            stream.last_activity_at = now

            if stream.flush_task is None or stream.flush_task.done():
                stream.flush_task = asyncio.create_task(self._flush_loop(key))

    async def _resolve_channel(
        self, *, channel_id: str, bridge_id: str, kind: str
    ) -> Any | None:
        channel: (
            discord.abc.GuildChannel
            | discord.abc.PrivateChannel
            | discord.Thread
            | None
        )
        try:
            channel = self._client.get_channel(int(channel_id))
        except Exception:
            channel = None
        if channel is None:
            try:
                channel = await self._client.fetch_channel(int(channel_id))
            except Exception:
                self._logger.info(
                    "voice transcript channel fetch failed channel_id=%s bridge_id=%s kind=%s",
                    channel_id,
                    bridge_id,
                    kind,
                )
                return None

        if not isinstance(
            channel, (discord.TextChannel, discord.Thread)
        ) and not hasattr(channel, "send"):
            self._logger.info(
                "voice transcript channel unsupported channel_id=%s type=%s",
                channel_id,
                type(channel).__name__,
            )
            return None
        return channel

    async def _flush_loop(self, key: tuple[str, str, str]) -> None:
        while True:
            await self._sleep(self._debounce_seconds)

            async with self._lock:
                stream = self._streams.get(key)
                if stream is None:
                    return
                quiet_for = self._clock() - stream.last_activity_at
                if quiet_for < self._debounce_seconds:
                    continue
                pending_text = _compact_text(" ".join(stream.pending_parts))
                stream.pending_parts = []
                if not pending_text:
                    stream.flush_task = None
                    return

                merged_text = _compact_text(f"{stream.message_text} {pending_text}")
                current_message = stream.message
                channel = stream.channel
                bridge_id = stream.bridge_id
                kind = stream.kind
                channel_id = key[2]

            tag = "🧑" if kind == "input" else "🤖"
            content = f"{tag} {merged_text}"[:2000]

            if current_message is None:
                posted = await self._send_rate_limit_safe(
                    channel=channel,
                    content=content,
                    bridge_id=bridge_id,
                    kind=kind,
                    channel_id=channel_id,
                )
                if posted is None:
                    async with self._lock:
                        stream = self._streams.get(key)
                        if stream is not None:
                            stream.flush_task = None
                    return
                async with self._lock:
                    stream = self._streams.get(key)
                    if stream is None:
                        return
                    stream.message = posted
                    stream.message_text = merged_text
                    stream.last_emit_at = self._clock()
            else:
                edited = await self._edit_rate_limit_safe(
                    message=current_message,
                    content=content,
                    bridge_id=bridge_id,
                    kind=kind,
                    channel_id=channel_id,
                )
                if edited is None:
                    async with self._lock:
                        stream = self._streams.get(key)
                        if stream is not None:
                            stream.flush_task = None
                    return
                async with self._lock:
                    stream = self._streams.get(key)
                    if stream is None:
                        return
                    stream.message = edited
                    stream.message_text = merged_text
                    stream.last_emit_at = self._clock()

            async with self._lock:
                stream = self._streams.get(key)
                if stream is None:
                    return
                if stream.pending_parts:
                    continue
                stream.flush_task = None
                return

    async def _send_rate_limit_safe(
        self,
        *,
        channel: Any,
        content: str,
        bridge_id: str,
        kind: str,
        channel_id: str,
    ) -> discord.Message | None:
        async def _send() -> discord.Message:
            return await channel.send(
                content, allowed_mentions=discord.AllowedMentions.none()
            )

        return await self._run_with_rate_limit_retry(
            operation="send",
            runner=_send,
            bridge_id=bridge_id,
            kind=kind,
            channel_id=channel_id,
        )

    async def _edit_rate_limit_safe(
        self,
        *,
        message: Any,
        content: str,
        bridge_id: str,
        kind: str,
        channel_id: str,
    ) -> Any | None:
        async def _edit() -> Any:
            return await message.edit(
                content=content, allowed_mentions=discord.AllowedMentions.none()
            )

        return await self._run_with_rate_limit_retry(
            operation="edit",
            runner=_edit,
            bridge_id=bridge_id,
            kind=kind,
            channel_id=channel_id,
        )

    async def _run_with_rate_limit_retry(
        self,
        *,
        operation: str,
        runner: Callable[[], Awaitable[Any]],
        bridge_id: str,
        kind: str,
        channel_id: str,
    ) -> Any | None:
        for attempt in (1, 2):
            try:
                return await runner()
            except Exception as exc:
                retry_after = self._extract_retry_after(exc)
                should_retry = retry_after is not None and attempt == 1
                self._logger.info(
                    "voice transcript %s failed bridge_id=%s kind=%s channel_id=%s attempt=%s retry_after=%s err=%s",
                    operation,
                    bridge_id,
                    kind,
                    channel_id,
                    attempt,
                    retry_after,
                    type(exc).__name__,
                )
                if not should_retry:
                    return None
                await self._sleep(max(0.0, float(retry_after)))
        return None

    @staticmethod
    def _extract_retry_after(exc: Exception) -> float | None:
        retry_after = getattr(exc, "retry_after", None)
        if isinstance(retry_after, (int, float)):
            return float(retry_after)

        status = getattr(exc, "status", None)
        if status == 429:
            text = str(getattr(exc, "text", "") or "")
            marker = "retry_after"
            if marker in text:
                pieces = text.split(marker, 1)[1]
                digits = "".join(ch for ch in pieces if ch.isdigit() or ch == ".")
                if digits:
                    try:
                        return float(digits)
                    except ValueError:
                        return 1.0
            return 1.0
        return None
