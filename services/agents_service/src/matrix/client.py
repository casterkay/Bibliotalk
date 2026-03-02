"""Minimal Matrix Client-Server API wrapper for appservice use.

This client authenticates using the application service token (`as_token`) and
optionally masquerades as a virtual user via the `user_id` query parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class MatrixSendResult:
    event_id: str


class MatrixClient:
    def __init__(
        self,
        *,
        homeserver_url: str,
        as_token: str,
        http_client: httpx.AsyncClient | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.homeserver_url = homeserver_url.rstrip("/")
        self.as_token = as_token
        self._client = http_client or httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self.homeserver_url}{path}"

    async def join_room_as(self, *, room_id: str, user_id: str) -> None:
        # POST /_matrix/client/v3/rooms/{roomId}/join
        response = await self._client.post(
            self._url(f"/_matrix/client/v3/rooms/{room_id}/join"),
            params={"access_token": self.as_token, "user_id": user_id},
            json={},
        )
        response.raise_for_status()

    async def send_message_as(
        self,
        *,
        room_id: str,
        user_id: str,
        content: dict[str, Any],
        txn_id: str,
    ) -> MatrixSendResult:
        # PUT /_matrix/client/v3/rooms/{roomId}/send/m.room.message/{txnId}
        response = await self._client.put(
            self._url(f"/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}"),
            params={"access_token": self.as_token, "user_id": user_id},
            json=content,
        )
        response.raise_for_status()
        body = response.json()
        return MatrixSendResult(event_id=str(body.get("event_id", "")))
