from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import aiohttp
import discord

from .voice_transcripts import VoiceTranscriptPublisher

logger = logging.getLogger("discord_service")


def _trim(value: str | None) -> str:
    return (value or "").strip()


def _to_ws_base(url: str) -> str:
    base = url.rstrip("/")
    if base.startswith("https://"):
        return f"wss://{base[8:]}"
    if base.startswith("http://"):
        return f"ws://{base[7:]}"
    return base


def _to_http_base(url: str) -> str:
    base = url.rstrip("/")
    if base.startswith("wss://"):
        return f"https://{base[6:]}"
    if base.startswith("ws://"):
        return f"http://{base[5:]}"
    return base


@dataclass(slots=True)
class ActiveVoiceBridge:
    bridge_id: str
    guild_id: str
    voice_channel_id: str
    agent_id: str
    text_channel_id: str | None
    text_thread_id: str | None
    websocket: aiohttp.ClientWebSocketResponse
    reader_task: asyncio.Task[None]


class DiscordVoiceGatewayProxy:
    def __init__(
        self,
        *,
        client: discord.Client,
        voip_service_url: str,
        transcript_publisher: VoiceTranscriptPublisher,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._http_base = _to_http_base(voip_service_url)
        self._ws_base = _to_ws_base(voip_service_url)
        self._transcripts = transcript_publisher
        self._logger = logger_ or logger
        self._session: aiohttp.ClientSession | None = None
        self._bridges_by_id: dict[str, ActiveVoiceBridge] = {}
        self._bridge_id_by_guild: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def ensure_bridge(
        self,
        *,
        guild_id: str,
        voice_channel_id: str,
        agent_id: str,
        initiator_user_id: str,
        text_channel_id: str | None,
        text_thread_id: str | None,
    ) -> ActiveVoiceBridge:
        reservation = f"pending:{uuid4()}"
        bridge_to_stop: ActiveVoiceBridge | None = None

        async with self._lock:
            existing_id = self._bridge_id_by_guild.get(guild_id)
            if existing_id:
                existing = self._bridges_by_id.get(existing_id)
                if (
                    existing
                    and existing.voice_channel_id == voice_channel_id
                    and existing.agent_id == agent_id
                ):
                    return existing
                bridge_to_stop = self._bridges_by_id.pop(existing_id, None)
                self._bridge_id_by_guild.pop(guild_id, None)

            self._bridge_id_by_guild[guild_id] = reservation

        if bridge_to_stop is not None:
            await self._stop_bridge(bridge_to_stop, reason="replaced")

        session = await self._ensure_session()
        ensure_url = f"{self._http_base}/v1/voip/ensure"
        body = {
            "platform": "discord",
            "guild_id": guild_id,
            "voice_channel_id": voice_channel_id,
            "agent_id": agent_id,
            "initiator_user_id": initiator_user_id,
            "text_channel_id": text_channel_id,
            "text_thread_id": text_thread_id,
        }
        bridge_id = ""
        ws: aiohttp.ClientWebSocketResponse | None = None
        try:
            async with session.post(
                ensure_url, json=body, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                try:
                    payload = await resp.json(content_type=None)
                except Exception:
                    payload = {"raw": await resp.text()}
                if resp.status >= 400:
                    raise RuntimeError(
                        f"voip ensure failed status={resp.status} payload={str(payload)[:2000]}"
                    )

            status = payload.get("status") if isinstance(payload, dict) else None
            bridge_id = _trim(
                (status or {}).get("bridge_id") if isinstance(status, dict) else ""
            )
            if not bridge_id:
                raise RuntimeError(
                    f"voip ensure missing bridge_id payload={str(payload)[:2000]}"
                )

            ws_url = f"{self._ws_base}/v1/discord/gateway/ws?bridge_id={bridge_id}"
            ws = await session.ws_connect(ws_url, heartbeat=15, autoping=True)

            async with self._lock:
                current = self._bridge_id_by_guild.get(guild_id)
                if current != reservation:
                    # Someone replaced us while we were performing network I/O.
                    # Best-effort stop to avoid leaking a VOIP bridge.
                    pass
                else:
                    reader_task = asyncio.create_task(
                        self._read_bridge_ws(bridge_id, ws)
                    )
                    bridge = ActiveVoiceBridge(
                        bridge_id=bridge_id,
                        guild_id=guild_id,
                        voice_channel_id=voice_channel_id,
                        agent_id=agent_id,
                        text_channel_id=_trim(text_channel_id) or None,
                        text_thread_id=_trim(text_thread_id) or None,
                        websocket=ws,
                        reader_task=reader_task,
                    )
                    self._bridges_by_id[bridge_id] = bridge
                    self._bridge_id_by_guild[guild_id] = bridge_id
                    return bridge
        except Exception:
            async with self._lock:
                if self._bridge_id_by_guild.get(guild_id) == reservation:
                    self._bridge_id_by_guild.pop(guild_id, None)

            if ws is not None and not ws.closed:
                await ws.close()
            if bridge_id:
                await self._request_voip_stop(
                    bridge_id=bridge_id, reason="ensure_failed"
                )
            raise

        if ws is not None and not ws.closed:
            await ws.close()
        if bridge_id:
            await self._request_voip_stop(bridge_id=bridge_id, reason="superseded")
        raise RuntimeError("voice bridge superseded by another ensure request")

    async def stop_guild(self, *, guild_id: str, reason: str = "requested") -> bool:
        bridge: ActiveVoiceBridge | None = None
        async with self._lock:
            bridge_id = self._bridge_id_by_guild.get(guild_id)
            if not bridge_id:
                return False
            bridge = self._bridges_by_id.pop(bridge_id, None)
            self._bridge_id_by_guild.pop(guild_id, None)

        if bridge is None:
            return False
        await self._stop_bridge(bridge, reason=reason)
        return True

    async def stop_all(self, *, reason: str = "shutdown") -> None:
        async with self._lock:
            bridges = list(self._bridges_by_id.values())
            self._bridges_by_id.clear()
            self._bridge_id_by_guild.clear()

        for bridge in bridges:
            await self._stop_bridge(bridge, reason=reason)

        try:
            await self._transcripts.close()
        except Exception:
            self._logger.info("voice transcript publisher close failed")

        async with self._lock:
            session = self._session
            self._session = None
        if session is not None and not session.closed:
            await session.close()

    async def status(
        self, *, guild_id: str | None = None
    ) -> list[dict[str, str | None]]:
        async with self._lock:
            rows = []
            for bridge in self._bridges_by_id.values():
                if guild_id and bridge.guild_id != guild_id:
                    continue
                rows.append(
                    {
                        "bridge_id": bridge.bridge_id,
                        "guild_id": bridge.guild_id,
                        "voice_channel_id": bridge.voice_channel_id,
                        "agent_id": bridge.agent_id,
                        "text_channel_id": bridge.text_channel_id,
                        "text_thread_id": bridge.text_thread_id,
                    }
                )
            return rows

    async def forward_gateway_dispatch(
        self, *, event_type: str, data: dict[str, Any]
    ) -> None:
        message_type = {
            "VOICE_STATE_UPDATE": "gateway.voice_state_update",
            "VOICE_SERVER_UPDATE": "gateway.voice_server_update",
        }.get(event_type)
        if not message_type:
            return

        guild_id = _trim(str(data.get("guild_id") or ""))
        if not guild_id:
            return

        websocket: aiohttp.ClientWebSocketResponse | None = None
        bridge_id = ""
        async with self._lock:
            bridge_id = self._bridge_id_by_guild.get(guild_id) or ""
            if not bridge_id:
                return
            bridge = self._bridges_by_id.get(bridge_id)
            if bridge is None or bridge.websocket.closed:
                return
            websocket = bridge.websocket

        if websocket is None or websocket.closed:
            return
        try:
            await websocket.send_str(
                json.dumps(
                    {
                        "type": message_type,
                        "payload": {"d": data},
                    }
                )
            )
        except Exception:
            self._logger.info(
                "forward gateway dispatch failed bridge_id=%s event=%s",
                bridge_id,
                event_type,
            )

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request_voip_stop(self, *, bridge_id: str, reason: str) -> None:
        session = await self._ensure_session()
        stop_url = f"{self._http_base}/v1/voip/stop"
        try:
            async with session.post(
                stop_url,
                json={"bridge_id": bridge_id, "reason": reason},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                await resp.read()
        except Exception:
            self._logger.info("voip stop request failed bridge_id=%s", bridge_id)

    async def _stop_bridge(self, bridge: ActiveVoiceBridge, *, reason: str) -> None:
        await self._request_voip_stop(bridge_id=bridge.bridge_id, reason=reason)

        if not bridge.websocket.closed:
            await bridge.websocket.close()
        if not bridge.reader_task.done():
            bridge.reader_task.cancel()

    async def _read_bridge_ws(
        self, bridge_id: str, websocket: aiohttp.ClientWebSocketResponse
    ) -> None:
        try:
            async for msg in websocket:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    body = json.loads(msg.data)
                except Exception:
                    continue
                if not isinstance(body, dict):
                    continue
                kind = str(body.get("type") or "")
                payload = body.get("payload") or {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    if kind == "gateway.request_change_voice_state":
                        await self._apply_voice_state(payload)
                        continue
                    if kind == "discord.transcription.input":
                        await self._transcripts.publish_input(payload)
                        continue
                    if kind == "discord.transcription.output":
                        await self._transcripts.publish_output(payload)
                except Exception:
                    self._logger.info(
                        "voice gateway message handling failed bridge_id=%s type=%s",
                        bridge_id,
                        kind,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._logger.exception(
                "voice gateway ws reader failed bridge_id=%s", bridge_id
            )
        finally:
            async with self._lock:
                bridge = self._bridges_by_id.pop(bridge_id, None)
                if bridge is not None:
                    self._bridge_id_by_guild.pop(bridge.guild_id, None)

    async def _apply_voice_state(self, payload: dict[str, Any]) -> None:
        guild_id = _trim(str(payload.get("guild_id") or ""))
        if not guild_id:
            return
        try:
            guild = self._client.get_guild(int(guild_id))
        except Exception:
            return
        if guild is None:
            self._logger.info(
                "voice state change ignored unknown guild_id=%s", guild_id
            )
            return

        channel_id_raw = payload.get("channel_id")
        channel: discord.VoiceChannel | discord.StageChannel | None
        if channel_id_raw is None:
            channel = None
        else:
            try:
                channel_id = int(str(channel_id_raw))
            except Exception:
                return
            candidate = guild.get_channel(channel_id)
            if candidate is None:
                try:
                    candidate = await self._client.fetch_channel(channel_id)
                except Exception:
                    return
            if not isinstance(candidate, (discord.VoiceChannel, discord.StageChannel)):
                self._logger.info(
                    "voice state change rejected non-voice channel guild_id=%s channel_id=%s",
                    guild_id,
                    channel_id,
                )
                return
            channel = candidate

        await guild.change_voice_state(
            channel=channel,
            self_mute=bool(payload.get("self_mute")),
            self_deaf=bool(payload.get("self_deaf")),
        )
