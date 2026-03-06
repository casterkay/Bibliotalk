"""Local E2E bootstrap tooling (Synapse + SQLite).

Usage examples (repo root):
  python -m agents_service.bootstrap seed-ghosts
  python -m agents_service.bootstrap import-segment-cache --cache-dir .ingestion_service/segment_cache
  python -m agents_service.bootstrap provision-matrix
  python -m agents_service.bootstrap post-profile-timeline
  python -m agents_service.bootstrap smoke-test --ghost confucius
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import httpx
import typer
import yaml
from bt_common.config import get_settings
from rich.console import Console

from .database.sqlalchemy_store import SQLAlchemyStore, SQLAlchemyStoreConfig, default_sqlite_url
from .matrix.client import MatrixClient

app = typer.Typer(add_completion=False)
console = Console()


def _repo_root() -> Path:
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    return start


def _default_segment_cache_dir() -> Path:
    return _repo_root() / ".ingestion_service" / "segment_cache"


def _load_roster(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ghosts = data.get("ghosts") or []
    if not isinstance(ghosts, list):
        raise typer.BadParameter(
            "roster file must contain a top-level 'ghosts: []' list"
        )
    return [g for g in ghosts if isinstance(g, dict)]


async def _store() -> SQLAlchemyStore:
    settings = get_settings()
    store = SQLAlchemyStore(
        config=SQLAlchemyStoreConfig(
            database_url=settings.DATABASE_URL or default_sqlite_url(),
            create_all=True,
        )
    )
    await store.init()
    return store


@dataclass
class MatrixAdminSession:
    homeserver_url: str
    access_token: str
    user_id: str


class MatrixAdminClient:
    def __init__(
        self, *, homeserver_url: str, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self.homeserver_url = homeserver_url.rstrip("/")
        self._http = http_client or httpx.AsyncClient(timeout=20.0)
        self._session: MatrixAdminSession | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    def _url(self, path: str) -> str:
        return f"{self.homeserver_url}{path}"

    async def login(self, *, username: str, password: str) -> MatrixAdminSession:
        resp = await self._http.post(
            self._url("/_matrix/client/v3/login"),
            json={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": username},
                "password": password,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        session = MatrixAdminSession(
            homeserver_url=self.homeserver_url,
            access_token=str(data["access_token"]),
            user_id=str(data["user_id"]),
        )
        self._session = session
        return session

    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._session:
            raise RuntimeError("MatrixAdminClient not logged in")
        resp = await self._http.request(
            method,
            self._url(path),
            headers={"Authorization": f"Bearer {self._session.access_token}"},
            json=json_body,
        )
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()

    async def create_room(
        self,
        *,
        name: str,
        topic: str | None = None,
        invite: list[str] | None = None,
        preset: str = "private_chat",
        is_direct: bool = False,
        creation_content: dict[str, Any] | None = None,
        initial_state: list[dict[str, Any]] | None = None,
        room_version: str | None = None,
        visibility: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "name": name,
            "preset": preset,
            "is_direct": is_direct,
        }
        if topic:
            payload["topic"] = topic
        if invite:
            payload["invite"] = invite
        if creation_content:
            payload["creation_content"] = creation_content
        if initial_state:
            payload["initial_state"] = initial_state
        if room_version:
            payload["room_version"] = room_version
        if visibility:
            payload["visibility"] = visibility

        data = await self._request(
            "POST", "/_matrix/client/v3/createRoom", json_body=payload
        )
        return str(data["room_id"])

    async def send_state(
        self,
        *,
        room_id: str,
        event_type: str,
        content: dict[str, Any],
        state_key: str | None = None,
    ) -> str:
        if state_key is None:
            path = f"/_matrix/client/v3/rooms/{room_id}/state/{event_type}"
        else:
            path = f"/_matrix/client/v3/rooms/{room_id}/state/{event_type}/{state_key}"
        data = await self._request("PUT", path, json_body=content)
        return str(data.get("event_id", ""))

    async def invite(self, *, room_id: str, user_id: str) -> None:
        await self._request(
            "POST",
            f"/_matrix/client/v3/rooms/{room_id}/invite",
            json_body={"user_id": user_id},
        )

    async def send_text(self, *, room_id: str, body: str) -> str:
        txn_id = uuid5(UUID("00000000-0000-0000-0000-000000000001"), body).hex
        data = await self._request(
            "PUT",
            f"/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
            json_body={"msgtype": "m.text", "body": body},
        )
        return str(data.get("event_id", ""))

    async def get_recent_messages(
        self, *, room_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not self._session:
            raise RuntimeError("MatrixAdminClient not logged in")
        resp = await self._http.get(
            self._url(f"/_matrix/client/v3/rooms/{room_id}/messages"),
            headers={"Authorization": f"Bearer {self._session.access_token}"},
            params={"dir": "b", "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        chunk = data.get("chunk") or []
        return chunk if isinstance(chunk, list) else []


@app.command("seed-ghosts")
def seed_ghosts(
    roster: Path = typer.Option(
        default_factory=lambda: _repo_root() / "deploy" / "local" / "ghosts.yaml",
        exists=False,
        help="YAML roster file (default: deploy/local/ghosts.yaml).",
    ),
    server_name: str | None = typer.Option(
        None,
        help="Matrix server name for user IDs (default: MATRIX_SERVER_NAME or 'localhost').",
    ),
    llm_model: str = typer.Option(
        "gemini-2.5-flash", help="Default model for seeded Ghosts."
    ),
) -> None:
    async def _run() -> None:
        settings = get_settings()
        matrix_domain = server_name or settings.MATRIX_SERVER_NAME or "localhost"
        if not roster.exists():
            raise typer.BadParameter(f"roster file not found: {roster}")

        store = await _store()
        try:
            ghosts = _load_roster(roster)
            if not ghosts:
                raise typer.BadParameter("roster contains no ghosts")

            for ghost in ghosts:
                tenant_prefix = str(
                    ghost.get("tenant_prefix") or ghost.get("slug") or ""
                ).strip()
                if not tenant_prefix:
                    raise typer.BadParameter("ghost missing tenant_prefix/slug")
                localpart = str(
                    ghost.get("matrix_localpart") or f"ghost_{tenant_prefix}"
                ).strip()
                display_name = str(
                    ghost.get("display_name") or tenant_prefix.title()
                ).strip()
                persona_prompt = str(
                    ghost.get("persona_prompt") or f"You are {display_name}."
                ).strip()
                kind = str(ghost.get("kind") or "figure").strip()
                model = str(ghost.get("llm_model") or llm_model).strip()
                is_active = bool(ghost.get("is_active", True))

                agent_uuid = uuid5(
                    UUID("00000000-0000-0000-0000-000000000000"),
                    f"bibliotalk:{tenant_prefix}",
                )
                matrix_user_id = f"@bt_{localpart}:{matrix_domain}"

                await store.upsert_agent(
                    agent_uuid=agent_uuid,
                    kind=kind,
                    display_name=display_name,
                    matrix_user_id=matrix_user_id,
                    persona_prompt=persona_prompt,
                    llm_model=model,
                    is_active=is_active,
                )
                await store.upsert_agent_emos_config(
                    agent_uuid=agent_uuid,
                    emos_base_url=settings.EMOS_BASE_URL,
                    tenant_prefix=tenant_prefix,
                    emos_api_key=settings.EMOS_API_KEY,
                )

                console.print(
                    f"Seeded {display_name} → {matrix_user_id} (tenant_prefix={tenant_prefix})"
                )
        finally:
            await store.aclose()

    asyncio.run(_run())


@app.command("import-segment-cache")
def import_segment_cache(
    cache_dir: Path = typer.Option(
        default_factory=_default_segment_cache_dir,
        exists=False,
        help="Directory containing .jsonl cache files (default: .ingestion_service/segment_cache).",
    ),
) -> None:
    async def _run() -> None:
        store = await _store()
        try:
            if not cache_dir.exists():
                raise typer.BadParameter(f"cache dir not found: {cache_dir}")

            files = sorted(cache_dir.glob("*.jsonl"))
            if not files:
                raise typer.BadParameter(f"no .jsonl files found in {cache_dir}")

            imported_sources = 0
            imported_segments = 0
            skipped = 0

            for path in files:
                tenant_prefix = path.stem
                agent = await store.get_agent_by_tenant_prefix(tenant_prefix)
                if not agent:
                    console.print(
                        f"Skip {path.name}: no agent for tenant_prefix={tenant_prefix}"
                    )
                    skipped += 1
                    continue
                agent_uuid = UUID(str(agent["id"]))

                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        payload = json.loads(line)
                        group_id = str(payload["group_id"])
                        platform = str(payload["platform"])
                        external_id = str(payload["external_id"])
                        title = str(
                            payload.get("group_name")
                            or payload.get("title")
                            or external_id
                        )
                        source_url = payload.get("source_url")

                        source = await store.upsert_source(
                            agent_uuid=agent_uuid,
                            emos_group_id=group_id,
                            platform=platform,
                            external_id=external_id,
                            external_url=str(source_url) if source_url else None,
                            title=title,
                            raw_meta={
                                k: payload.get(k)
                                for k in ("group_name", "source_url")
                                if payload.get(k) is not None
                            },
                        )
                        imported_sources += 1

                        await store.upsert_segment(
                            agent_uuid=agent_uuid,
                            source_uuid=UUID(str(source["id"])),
                            emos_message_id=str(payload["message_id"]),
                            platform=platform,
                            seq=int(payload["seq"]),
                            text=str(payload["content"]),
                            sha256=str(payload["sha256"]),
                            speaker=payload.get("speaker"),
                            start_ms=payload.get("start_ms"),
                            end_ms=payload.get("end_ms"),
                            source_title=title,
                            source_url=str(source_url) if source_url else None,
                        )
                        imported_segments += 1

            console.print(
                f"Imported segments: sources={imported_sources} segments={imported_segments} skipped_files={skipped}"
            )
        finally:
            await store.aclose()

    asyncio.run(_run())


@app.command("provision-matrix")
def provision_matrix(
    create_space: bool = typer.Option(
        True, help="Create a Bibliotalk Space and add rooms as children."
    ),
    space_name: str = typer.Option("Bibliotalk", help="Space name."),
    group_room_name: str = typer.Option(
        "Bibliotalk — Group Chat", help="Group chat room name."
    ),
) -> None:
    async def _run() -> None:
        settings = get_settings()
        if not settings.MATRIX_ADMIN_USER or not settings.MATRIX_ADMIN_PASSWORD:
            raise typer.BadParameter("MATRIX_ADMIN_USER/PASSWORD not set")

        store = await _store()
        matrix_admin = MatrixAdminClient(homeserver_url=settings.MATRIX_HOMESERVER_URL)
        matrix_as = MatrixClient(
            homeserver_url=settings.MATRIX_HOMESERVER_URL,
            as_token=settings.MATRIX_AS_TOKEN,
        )
        try:
            session = await matrix_admin.login(
                username=settings.MATRIX_ADMIN_USER,
                password=settings.MATRIX_ADMIN_PASSWORD,
            )

            agents = await store.list_agents(active_only=True)
            if not agents:
                raise typer.BadParameter(
                    "No active agents found in the SQLite store (run seed-ghosts first)"
                )

            space_room_id: str | None = None
            if create_space:
                space_room_id = await matrix_admin.create_room(
                    name=space_name,
                    preset="private_chat",
                    creation_content={"type": "m.space"},
                )
                console.print(f"Created space: {space_room_id}")

            ghost_user_ids = [
                str(a.get("matrix_user_id")) for a in agents if a.get("matrix_user_id")
            ]
            group_room_id = await matrix_admin.create_room(
                name=group_room_name,
                preset="private_chat",
                invite=ghost_user_ids,
            )
            for ghost_user_id in ghost_user_ids:
                await matrix_as.join_room_as(
                    room_id=group_room_id, user_id=ghost_user_id
                )
            console.print(f"Created group room: {group_room_id}")

            if space_room_id:
                await matrix_admin.send_state(
                    room_id=space_room_id,
                    event_type="m.space.child",
                    state_key=group_room_id,
                    content={"via": [settings.MATRIX_SERVER_NAME or "localhost"]},
                )

            for agent in agents:
                agent_uuid = UUID(str(agent["id"]))
                ghost_user_id = str(agent["matrix_user_id"])

                existing = await store.get_profile_room_for_agent(agent_uuid)
                if existing and existing.get("matrix_room_id"):
                    profile_room_id = str(existing["matrix_room_id"])
                    console.print(
                        f"Reuse profile room: {agent['display_name']} → {profile_room_id}"
                    )
                else:
                    profile_room_id = await matrix_admin.create_room(
                        name=f"{agent['display_name']} — Profile",
                        preset="public_chat",
                        visibility="public",
                        invite=[ghost_user_id],
                    )
                    await matrix_as.join_room_as(
                        room_id=profile_room_id, user_id=ghost_user_id
                    )

                    # Make room read-only for default users; only admin + ghost can send.
                    await matrix_admin.send_state(
                        room_id=profile_room_id,
                        event_type="m.room.power_levels",
                        content={
                            "users": {session.user_id: 100, ghost_user_id: 100},
                            "users_default": 0,
                            "events_default": 100,
                            "state_default": 100,
                            "ban": 100,
                            "kick": 100,
                            "redact": 100,
                            "invite": 100,
                        },
                    )

                    await store.upsert_profile_room(
                        agent_uuid=agent_uuid,
                        matrix_room_id=profile_room_id,
                    )
                    console.print(
                        f"Created profile room: {agent['display_name']} → {profile_room_id}"
                    )

                if space_room_id:
                    await matrix_admin.send_state(
                        room_id=space_room_id,
                        event_type="m.space.child",
                        state_key=profile_room_id,
                        content={"via": [settings.MATRIX_SERVER_NAME or "localhost"]},
                    )

        finally:
            await store.aclose()
            await matrix_admin.aclose()
            await matrix_as.aclose()

    asyncio.run(_run())


@app.command("post-profile-timeline")
def post_profile_timeline(
    max_segments_per_source: int = typer.Option(
        5, help="Max segments to post per source."
    ),
    max_sources: int = typer.Option(5, help="Max sources to post per agent."),
) -> None:
    async def _run() -> None:
        settings = get_settings()
        store = await _store()
        matrix_as = MatrixClient(
            homeserver_url=settings.MATRIX_HOMESERVER_URL,
            as_token=settings.MATRIX_AS_TOKEN,
        )
        try:
            agents = await store.list_agents(active_only=True)
            for agent in agents:
                agent_uuid = UUID(str(agent["id"]))
                ghost_user_id = str(agent["matrix_user_id"])
                profile = await store.get_profile_room_for_agent(agent_uuid)
                if not profile or not profile.get("matrix_room_id"):
                    console.print(
                        f"Skip {agent['display_name']}: no profile room (run provision-matrix)"
                    )
                    continue
                room_id = str(profile["matrix_room_id"])

                segments = await store.get_segments_for_agent(agent_uuid)
                if not segments:
                    console.print(
                        f"Skip {agent['display_name']}: no segments (run import-segment-cache)"
                    )
                    continue

                # Group by source_id and keep stable ordering.
                by_source: dict[str, list[dict[str, Any]]] = {}
                for row in sorted(
                    segments,
                    key=lambda r: (str(r.get("source_id")), int(r.get("seq") or 0)),
                ):
                    source_id = str(row.get("source_id") or "")
                    if not source_id:
                        continue
                    by_source.setdefault(source_id, []).append(row)

                posted = 0
                for source_idx, (source_id, rows) in enumerate(by_source.items()):
                    if source_idx >= max_sources:
                        break
                    root_event_id: str | None = None
                    for row_idx, row in enumerate(rows[:max_segments_per_source]):
                        if row.get("matrix_event_id"):
                            if row_idx == 0:
                                root_event_id = str(row["matrix_event_id"])
                            continue

                        content: dict[str, Any] = {
                            "msgtype": "m.text",
                            "body": str(row.get("text") or ""),
                        }
                        if row_idx > 0 and root_event_id:
                            content["m.relates_to"] = {
                                "rel_type": "m.thread",
                                "event_id": root_event_id,
                                "is_falling_back": True,
                                "m.in_reply_to": {"event_id": root_event_id},
                            }
                        content["com.bibliotalk.segment"] = {
                            "emos_message_id": row.get("emos_message_id"),
                            "source_title": row.get("source_title"),
                            "source_url": row.get("source_url"),
                            "platform": row.get("platform"),
                            "seq": row.get("seq"),
                        }

                        result = await matrix_as.send_message_as(
                            room_id=room_id,
                            user_id=ghost_user_id,
                            content=content,
                            txn_id=uuid5(
                                UUID("00000000-0000-0000-0000-000000000002"),
                                str(row.get("emos_message_id")),
                            ).hex,
                        )
                        event_id = result.event_id
                        if row_idx == 0:
                            root_event_id = event_id

                        await store.upsert_segment(
                            agent_uuid=agent_uuid,
                            source_uuid=UUID(str(row["source_id"])),
                            emos_message_id=str(row["emos_message_id"]),
                            platform=str(row["platform"]),
                            seq=int(row["seq"]),
                            text=str(row["text"]),
                            sha256=str(row["sha256"]),
                            speaker=row.get("speaker"),
                            start_ms=row.get("start_ms"),
                            end_ms=row.get("end_ms"),
                            source_title=row.get("source_title"),
                            source_url=row.get("source_url"),
                            matrix_event_id=event_id,
                        )
                        posted += 1

                console.print(
                    f"Posted {posted} profile segments for {agent['display_name']}"
                )

        finally:
            await store.aclose()
            await matrix_as.aclose()

    asyncio.run(_run())


@app.command("smoke-test")
def smoke_test(
    ghost: str = typer.Option(
        "confucius", help="Ghost tenant_prefix to DM (must exist in the SQLite store)."
    ),
    prompt: str = typer.Option(
        "What did you say about learning?", help="Message text."
    ),
    timeout_s: int = typer.Option(20, help="How long to wait for a reply."),
) -> None:
    async def _run() -> None:
        settings = get_settings()
        if not settings.MATRIX_ADMIN_USER or not settings.MATRIX_ADMIN_PASSWORD:
            raise typer.BadParameter("MATRIX_ADMIN_USER/PASSWORD not set")

        store = await _store()
        matrix_admin = MatrixAdminClient(homeserver_url=settings.MATRIX_HOMESERVER_URL)
        matrix_as = MatrixClient(
            homeserver_url=settings.MATRIX_HOMESERVER_URL,
            as_token=settings.MATRIX_AS_TOKEN,
        )
        try:
            await matrix_admin.login(
                username=settings.MATRIX_ADMIN_USER,
                password=settings.MATRIX_ADMIN_PASSWORD,
            )
            agent = await store.get_agent_by_tenant_prefix(ghost)
            if not agent:
                raise typer.BadParameter(
                    f"Unknown ghost tenant_prefix={ghost} (run seed-ghosts)"
                )
            ghost_user_id = str(agent["matrix_user_id"])

            room_id = await matrix_admin.create_room(
                name=f"DM — {agent['display_name']}",
                preset="private_chat",
                is_direct=True,
                invite=[ghost_user_id],
            )
            await matrix_as.join_room_as(room_id=room_id, user_id=ghost_user_id)
            await matrix_admin.send_text(room_id=room_id, body=prompt)

            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                events = await matrix_admin.get_recent_messages(
                    room_id=room_id, limit=20
                )
                for ev in events:
                    if ev.get("type") != "m.room.message":
                        continue
                    if ev.get("sender") != ghost_user_id:
                        continue
                    content = ev.get("content") or {}
                    body = content.get("body") or ""
                    citations = (content.get("com.bibliotalk.citations") or {}).get(
                        "items"
                    ) or []
                    console.print(f"Reply: {body}")
                    console.print(f"Citations: {len(citations)}")
                    return
                await asyncio.sleep(1.0)

            raise RuntimeError(
                "Timed out waiting for ghost reply (is agents_service running?)"
            )
        finally:
            await store.aclose()
            await matrix_admin.aclose()
            await matrix_as.aclose()

    asyncio.run(_run())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
