from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

DEFAULT_GEMINI_LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"


@dataclass(frozen=True, slots=True)
class GeminiLiveConfig:
    google_api_key: str
    model: str = DEFAULT_GEMINI_LIVE_MODEL


class GeminiLiveBackend:
    """Gemini Live backend placeholder.

    The Matrix MVP contract requires bidirectional audio + transcription streaming.
    This module provides the integration seam; the actual Gemini Live wiring is
    intentionally implemented behind this interface.
    """

    def __init__(self, _config: GeminiLiveConfig):
        self._config = _config
        self._session_cm: Any | None = None
        self._session: Any | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._receiver_task: asyncio.Task | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return

        from google import genai

        client = genai.Client(api_key=self._config.google_api_key)
        config = {
            "response_modalities": ["AUDIO"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }

        self._session_cm = client.aio.live.connect(model=self._config.model, config=config)
        self._session = await self._session_cm.__aenter__()
        self._receiver_task = asyncio.create_task(self._receiver_loop())

    async def send_audio_chunk(self, *, pcm16k: bytes) -> None:
        await self.connect()
        assert self._session is not None
        from google.genai import types

        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm16k, mime_type="audio/pcm;rate=16000")
        )

    async def send_text(self, *, text: str) -> None:
        await self.connect()
        assert self._session is not None
        await self._session.send_realtime_input(text=text)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self._queue.get()

    async def _receiver_loop(self) -> None:
        assert self._session is not None

        async for msg in self._session.receive():
            server_content = getattr(msg, "server_content", None)
            if not server_content:
                continue

            model_turn = getattr(server_content, "model_turn", None)
            parts = getattr(model_turn, "parts", None) if model_turn else None
            if parts:
                for part in parts:
                    inline_data = getattr(part, "inline_data", None)
                    if not inline_data:
                        continue
                    mime_type = getattr(inline_data, "mime_type", "") or ""
                    data = getattr(inline_data, "data", None)
                    if data is None:
                        continue
                    if mime_type.startswith("audio/pcm"):
                        self._queue.put_nowait(
                            {"type": "audio", "mime_type": mime_type, "data": data}
                        )

            input_tx = getattr(server_content, "input_transcription", None)
            if input_tx and getattr(input_tx, "text", None):
                self._queue.put_nowait({"type": "transcription.input", "text": input_tx.text})

            output_tx = getattr(server_content, "output_transcription", None)
            if output_tx and getattr(output_tx, "text", None):
                self._queue.put_nowait({"type": "transcription.output", "text": output_tx.text})

    async def aclose(self) -> None:
        if self._receiver_task and not self._receiver_task.done():
            self._receiver_task.cancel()
        self._receiver_task = None

        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            finally:
                self._session_cm = None
                self._session = None
