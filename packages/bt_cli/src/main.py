from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote as _urlquote
from urllib.request import Request as _UrlRequest
from urllib.request import urlopen as _urlopen

import typer
from bt_store.engine import init_database, resolve_database_path, session_scope
from bt_store.models import Agent
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

app = typer.Typer(
    no_args_is_help=True,
    help="Bibliotalk unified operator CLI (YouTube → EverMemOS → Discord).",
)
console = Console()


@dataclass(frozen=True, slots=True)
class _JsonResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


def _print_json(result: _JsonResult) -> None:
    payload = {"ok": result.ok, "data": result.data, "error": result.error}
    console.print(json.dumps(payload, ensure_ascii=False))


def _run(coro) -> Any:
    return asyncio.run(coro)


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _http_json(
    method: str, url: str, *, body: dict[str, Any] | None, headers: dict[str, str]
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = _UrlRequest(url, method=method, data=data, headers=headers)
    try:
        with _urlopen(req, timeout=20) as resp:
            payload = resp.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - operator-friendly errors
        raise RuntimeError(f"HTTP {method} {url} failed: {exc}") from exc
    try:
        return json.loads(payload)
    except Exception as exc:  # pragma: no cover - operator-friendly errors
        raise RuntimeError(f"Invalid JSON from {method} {url}: {payload[:2000]}") from exc


class _MatrixAdminClient:
    def __init__(
        self, *, homeserver_url: str, server_name: str, admin_user: str, admin_password: str
    ):
        self._homeserver_url = homeserver_url.rstrip("/")
        self._server_name = server_name
        self._admin_user = admin_user
        self._admin_password = admin_password
        self._access_token: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise RuntimeError("Not logged in")
        return {"content-type": "application/json", "authorization": f"Bearer {self._access_token}"}

    def login(self) -> None:
        url = f"{self._homeserver_url}/_matrix/client/v3/login"
        res = _http_json(
            "POST",
            url,
            body={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": self._admin_user},
                "password": self._admin_password,
            },
            headers={"content-type": "application/json"},
        )
        token = str(res.get("access_token") or "")
        if not token:
            raise RuntimeError(f"Login failed; response missing access_token: {res}")
        self._access_token = token

    def _ensure_logged_in(self) -> None:
        if self._access_token is None:
            self.login()

    def ensure_room_by_alias(self, *, alias_localpart: str, name: str, is_space: bool) -> str:
        self._ensure_logged_in()
        alias = f"#{alias_localpart}:{self._server_name}"

        create_url = f"{self._homeserver_url}/_matrix/client/v3/createRoom"
        payload: dict[str, Any] = {
            "name": name,
            "preset": "public_chat",
            "visibility": "public",
            "room_alias_name": alias_localpart,
        }
        if is_space:
            payload["topic"] = "Bibliotalk dev space"
            payload["creation_content"] = {"type": "m.space"}

        try:
            res = _http_json("POST", create_url, body=payload, headers=self._auth_headers())
            room_id = str(res.get("room_id") or "")
            if room_id:
                return room_id
        except Exception:
            # Alias likely already exists; resolve it below.
            pass

        alias_enc = _urlquote(alias, safe="")
        dir_url = f"{self._homeserver_url}/_matrix/client/v3/directory/room/{alias_enc}"
        res = _http_json("GET", dir_url, body=None, headers=self._auth_headers())
        room_id = str(res.get("room_id") or "")
        if not room_id:
            raise RuntimeError(f"Failed to resolve alias {alias}: {res}")
        return room_id

    def link_child(self, *, space_room_id: str, child_room_id: str) -> None:
        self._ensure_logged_in()
        url = (
            f"{self._homeserver_url}/_matrix/client/v3/rooms/{_urlquote(space_room_id, safe='')}"
            f"/state/m.space.child/{_urlquote(child_room_id, safe='')}"
        )
        _http_json(
            "PUT",
            url,
            body={"via": [self._server_name], "suggested": True},
            headers=self._auth_headers(),
        )

    def invite(self, *, room_id: str, user_id: str) -> None:
        self._ensure_logged_in()
        url = f"{self._homeserver_url}/_matrix/client/v3/rooms/{_urlquote(room_id, safe='')}/invite"
        _http_json("POST", url, body={"user_id": user_id}, headers=self._auth_headers())


@app.command()
def db_init(
    db: str | None = typer.Option(None, "--db", help="SQLite path (overrides BIBLIOTALK_DB_PATH)."),
    json_: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Create DB tables (dev-friendly; migrations recommended for prod)."""
    try:
        _run(init_database(db))
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(_JsonResult(ok=True, data={"db_path": str(resolve_database_path(db))}))
    else:
        console.print(f"Initialized DB at `{resolve_database_path(db)}`")


matrix_app = typer.Typer(no_args_is_help=True, help="Matrix operations.")
app.add_typer(matrix_app, name="matrix")

matrix_demo_app = typer.Typer(no_args_is_help=True, help="Matrix demo helpers.")
matrix_app.add_typer(matrix_demo_app, name="demo")


@matrix_demo_app.command("provision")
def matrix_demo_provision(
    figures: str = typer.Option(
        "alan-watts,steve-jobs", "--figures", help="Comma-separated figure slugs."
    ),
    db: str | None = typer.Option(None, "--db", help="SQLite path (overrides BIBLIOTALK_DB_PATH)."),
    matrix_env: str = typer.Option(
        "deploy/local/matrix/.env",
        "--matrix-env",
        help="Path to local Matrix stack .env (from ./scripts/matrix-dev.sh init).",
    ),
    out: str = typer.Option(
        ".bibliotalk/matrix_demo_mapping.json",
        "--out",
        help="Write a gitignored mapping file for ops convenience.",
    ),
    json_: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Provision local Matrix demo Figure Rooms under the Bibliotalk Space."""
    figure_slugs = [s.strip() for s in figures.split(",") if s.strip()]
    if not figure_slugs:
        raise typer.BadParameter("--figures must not be empty")

    matrix_env_path = Path(matrix_env)
    env_map = _parse_dotenv(matrix_env_path)

    server_name = (env_map.get("MATRIX_SERVER_NAME") or "localhost").strip() or "localhost"
    homeserver_url = (env_map.get("MATRIX_HOMESERVER_URL") or "http://localhost:8008").strip()
    admin_user = (env_map.get("MATRIX_ADMIN_USER") or "admin").strip()
    admin_password = (env_map.get("MATRIX_ADMIN_PASSWORD") or "").strip()
    spirit_user_prefix = (env_map.get("MATRIX_SPIRIT_USER_PREFIX") or "bt_").strip() or "bt_"

    if not admin_password:
        raise typer.BadParameter(
            f"Missing MATRIX_ADMIN_PASSWORD in {matrix_env_path} (run: ./scripts/matrix-dev.sh init)"
        )

    default_display_names: dict[str, str] = {
        "alan-watts": "Alan Watts",
        "steve-jobs": "Steve Jobs",
    }

    async def _ensure_agents() -> dict[str, str]:
        await init_database(db)
        ids: dict[str, str] = {}
        async with session_scope(db) as session:
            for slug in figure_slugs:
                display_name = default_display_names.get(slug) or slug.replace("-", " ").title()
                row = (
                    await session.execute(select(Agent).where(Agent.slug == slug))
                ).scalar_one_or_none()
                if row is None:
                    row = Agent(slug=slug, display_name=display_name, kind="figure")
                    session.add(row)
                    await session.flush()
                ids[slug] = str(row.agent_id)
            await session.commit()
        return ids

    try:
        agent_ids = _run(_ensure_agents())
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc

    mx = _MatrixAdminClient(
        homeserver_url=homeserver_url,
        server_name=server_name,
        admin_user=admin_user,
        admin_password=admin_password,
    )

    try:
        space_room_id = mx.ensure_room_by_alias(
            alias_localpart="bibliotalk-space", name="Bibliotalk", is_space=True
        )

        rooms: list[dict[str, str]] = []
        for slug in figure_slugs:
            agent_id = agent_ids[slug]
            room_alias_localpart = f"{spirit_user_prefix}{slug}"
            room_name = default_display_names.get(slug) or slug.replace("-", " ").title()
            room_id = mx.ensure_room_by_alias(
                alias_localpart=room_alias_localpart, name=room_name, is_space=False
            )
            mx.link_child(space_room_id=space_room_id, child_room_id=room_id)

            spirit_user_id = f"@{spirit_user_prefix}{agent_id}:{server_name}"
            mx.invite(room_id=room_id, user_id=spirit_user_id)

            rooms.append(
                {
                    "slug": slug,
                    "agent_id": agent_id,
                    "spirit_user_id": spirit_user_id,
                    "room_id": room_id,
                    "canonical_alias": f"#{room_alias_localpart}:{server_name}",
                }
            )

        out_path = Path(out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"space_room_id": space_room_id, "rooms": rooms}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc

    data = {"space_room_id": space_room_id, "rooms": rooms, "out": str(out_path)}
    if json_:
        _print_json(_JsonResult(ok=True, data=data))
    else:
        console.print(f"Provisioned Space `{space_room_id}` and {len(rooms)} Figure Rooms.")
        console.print(f"Wrote mapping `{out_path}`")


agent_app = typer.Typer(no_args_is_help=True, help="Agent operations.")
app.add_typer(agent_app, name="agent")


@agent_app.command("seed")
def agent_seed(
    agent: str = typer.Option(..., "--agent", help="Agent slug (EMOS user_id), e.g. alan-watts."),
    kind: str = typer.Option("figure", "--kind", help="Agent kind: figure|user."),
    subscription_url: str = typer.Option(
        ..., "--subscription-url", help="YouTube channel/playlist URL."
    ),
    guild_id: str = typer.Option(..., "--guild-id", help="Discord guild ID to host feeds/talks."),
    channel_id: str = typer.Option(
        ..., "--channel-id", help="Discord feed channel ID for this agent."
    ),
    display_name: str | None = typer.Option(None, "--display-name"),
    persona_summary: str | None = typer.Option(None, "--persona-summary"),
    subscription_type: str = typer.Option("channel", "--subscription-type"),
    poll_interval_minutes: int = typer.Option(60, "--poll-interval-minutes"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Seed (or update) an agent, subscription, and Discord mapping."""
    if not json_:
        console.print(
            f"Seeding `{agent}` (subscription: `{subscription_url}`, guild: `{guild_id}`, channel: `{channel_id}`)..."
        )
    try:
        from discord_service.ops import seed_agent

        _run(
            seed_agent(
                db_path=db,
                agent_slug=agent,
                kind=kind,
                display_name=display_name,
                persona_summary=persona_summary,
                subscription_url=subscription_url,
                subscription_type=subscription_type,
                guild_id=guild_id,
                channel_id=channel_id,
                poll_interval_minutes=poll_interval_minutes,
            )
        )
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc

    if json_:
        _print_json(
            _JsonResult(
                ok=True,
                data={
                    "agent": agent,
                    "kind": kind,
                    "subscription_url": subscription_url,
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "db_path": str(resolve_database_path(db)),
                },
            )
        )
    else:
        console.print(
            f"Seeded `{agent}` with subscription `{subscription_url}` and feed channel `{channel_id}`."
        )


ingest_app = typer.Typer(no_args_is_help=True, help="Ingest operations.")
app.add_typer(ingest_app, name="ingest")


@ingest_app.command("request")
def ingest_request(
    agent: str = typer.Option(..., "--agent"),
    video_id: str = typer.Option(..., "--video-id"),
    title: str = typer.Option("(manual ingest requested)", "--title"),
    source_url: str | None = typer.Option(None, "--source-url"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Request a manual one-shot ingest for a YouTube video."""
    try:
        from memory_service.ops import request_manual_ingest

        _run(
            request_manual_ingest(
                db_path=db,
                agent_slug=agent,
                external_id=video_id,
                title=title,
                source_url=source_url,
            )
        )
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(_JsonResult(ok=True, data={"agent": agent, "video_id": video_id}))
    else:
        console.print(
            f"Manual ingest requested for `{agent}` video `{video_id}`. Run `bibliotalk collector run --once` to process."
        )


collector_app = typer.Typer(no_args_is_help=True, help="Collector runtime (memory_service).")
app.add_typer(collector_app, name="collector")


@collector_app.command("run")
def collector_run(
    agent: str | None = typer.Option(None, "--agent", help="Only run for one agent slug."),
    db: str | None = typer.Option(None, "--db"),
    log_level: str | None = typer.Option(None, "--log-level"),
    once: bool = typer.Option(False, "--once"),
) -> None:
    """Run the collector (poll subscriptions, ingest, memorize)."""
    from memory_service.entrypoint import run_collector

    raise typer.Exit(
        code=int(
            _run(
                run_collector(
                    agent_slug=agent,
                    db_path=db,
                    log_level=log_level,
                    once=once,
                )
            )
        )
    )


discord_app = typer.Typer(no_args_is_help=True, help="Discord runtime (discord_service).")
app.add_typer(discord_app, name="discord")


@discord_app.command("run")
def discord_run(
    db: str | None = typer.Option(None, "--db"),
    log_level: str | None = typer.Option(None, "--log-level"),
    command_guild_id: str | None = typer.Option(None, "--command-guild-id"),
    voip_service_url: str | None = typer.Option(None, "--voip-service-url"),
    voice_default_text_channel_id: str | None = typer.Option(
        None, "--voice-default-text-channel-id"
    ),
) -> None:
    """Run the Discord bot runtime."""
    from discord_service.entrypoint import run_discord_bot

    raise typer.Exit(
        code=int(
            _run(
                run_discord_bot(
                    db_path=db,
                    log_level=log_level,
                    discord_command_guild_id=command_guild_id,
                    voip_service_url=voip_service_url,
                    discord_voice_default_text_channel_id=voice_default_text_channel_id,
                )
            )
        )
    )


memories_app = typer.Typer(no_args_is_help=True, help="Memories HTTP API (memory_service).")
app.add_typer(memories_app, name="memories")


@memories_app.command("run")
def memories_run(
    db: str | None = typer.Option(None, "--db"),
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Run the Memories HTTP API."""
    from memory_service.api.entrypoint import run_memories_api

    raise typer.Exit(
        code=int(
            _run(
                run_memories_api(
                    db_path=db,
                    host=host,
                    port=port,
                    log_level=log_level,
                )
            )
        )
    )


webui_app = typer.Typer(no_args_is_help=True, help="Operator Web UI (bt_webui).")
app.add_typer(webui_app, name="webui")


@webui_app.command("run")
def webui_run(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8090, "--port"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Run the operator admin panel (FastAPI serving a static UI + /api)."""
    from bt_webui.entrypoint import run_webui

    raise typer.Exit(code=int(_run(run_webui(host=host, port=port, log_level=log_level or "INFO"))))


feed_app = typer.Typer(no_args_is_help=True, help="Discord feed operations.")
app.add_typer(feed_app, name="feed")


@feed_app.command("publish")
def feed_publish(
    db: str | None = typer.Option(None, "--db"),
    log_level: str | None = typer.Option(None, "--log-level"),
    agent: str | None = typer.Option(None, "--agent", help="Only publish for one agent slug."),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Publish all pending feed posts (connects to Discord, publishes, exits)."""
    from discord_service.config import load_runtime_config as load_discord_config
    from discord_service.ops.feed import publish_pending_feeds_once

    config = load_discord_config(db_path=db, log_level=log_level, discord_command_guild_id=None)
    try:
        summary = _run(publish_pending_feeds_once(config, agent_slug=agent))
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc

    if json_:
        _print_json(_JsonResult(ok=True, data=asdict(summary)))
        return
    table = Table(title="Feed publication")
    table.add_column("attempted_agents")
    table.add_column("attempted_sources")
    table.add_column("published_sources")
    table.add_column("failed_sources")
    table.add_row(
        str(summary.attempted_agents),
        str(summary.attempted_sources),
        str(summary.published_sources),
        str(summary.failed_sources),
    )
    console.print(table)


matrix_app = typer.Typer(no_args_is_help=True, help="Matrix adapter runtime (matrix_service).")
app.add_typer(matrix_app, name="matrix")


@matrix_app.command("run")
def matrix_run(
    port: int = typer.Option(9009, "--port", help="matrix_service bind port."),
    host: str = typer.Option("0.0.0.0", "--host", help="matrix_service bind host."),
    install: bool = typer.Option(False, "--install", help="Run `npm install` before starting."),
) -> None:
    """Run the Matrix adapter (Node/TS appservice)."""
    repo_root = Path(__file__).resolve().parents[3]
    service_dir = repo_root / "services" / "matrix_service"
    if not service_dir.is_dir():
        raise typer.Exit(code=2)

    env = os.environ.copy()
    env.setdefault("MATRIX_SERVICE_HOST", host)
    env.setdefault("MATRIX_SERVICE_PORT", str(port))

    if install:
        subprocess.run(["npm", "install"], cwd=service_dir, env=env, check=True)

    result = subprocess.run(["npm", "run", "dev"], cwd=service_dir, env=env)
    raise typer.Exit(code=int(result.returncode))


@feed_app.command("status")
def feed_status(
    agent: str = typer.Option(..., "--agent"),
    video_id: str = typer.Option(..., "--video-id"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Show feed publishing status for one video."""
    try:
        from discord_service.ops.feed import source_feed_status_by_video

        status = _run(source_feed_status_by_video(db_path=db, agent_slug=agent, video_id=video_id))
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(_JsonResult(ok=True, data=asdict(status)))
    else:
        console.print(f"source_id={status.source_id} parent_posted={status.parent_posted}")
        console.print(
            f"batches_total={status.batches_total} batches_posted={status.batches_posted} failed_posts={status.failed_posts}"
        )


@feed_app.command("retry-failed")
def feed_retry_failed(
    agent: str = typer.Option(..., "--agent"),
    video_id: str = typer.Option(..., "--video-id"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Mark failed feed posts as pending and republish missing parts."""
    from discord_service.config import load_runtime_config as load_discord_config
    from discord_service.ops.feed import retry_failed_posts_by_video

    config = load_discord_config(db_path=db, log_level=None, discord_command_guild_id=None)
    try:
        summary = _run(
            retry_failed_posts_by_video(
                db_path=db,
                agent_slug=agent,
                video_id=video_id,
                discord_config=config,
            )
        )
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(_JsonResult(ok=True, data=asdict(summary)))
    else:
        console.print(
            f"Retry complete `{agent}` `{video_id}` published={summary.published_sources} failed={summary.failed_sources}."
        )


@feed_app.command("republish")
def feed_republish(
    agent: str = typer.Option(..., "--agent"),
    video_id: str = typer.Option(..., "--video-id"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Publish/resume feed posting for a single video (idempotent)."""
    from discord_service.config import load_runtime_config as load_discord_config
    from discord_service.ops.feed import republish_source_by_video

    config = load_discord_config(db_path=db, log_level=None, discord_command_guild_id=None)
    try:
        result = _run(
            republish_source_by_video(
                db_path=db,
                agent_slug=agent,
                video_id=video_id,
                discord_config=config,
            )
        )
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(
            _JsonResult(ok=True, data={"status": result.status, "source_id": str(result.source_id)})
        )
    else:
        console.print(f"Republish result `{agent}` `{video_id}` status={result.status}.")


talks_app = typer.Typer(no_args_is_help=True, help="Talk thread operations.")
app.add_typer(talks_app, name="talks")


@talks_app.command("list")
def talks_list(
    owner_discord_user_id: str = typer.Option(..., "--user-id", help="Discord user ID."),
    limit: int = typer.Option(10, "--limit"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List recent talks for a user (operator/debug helper)."""
    try:
        from discord_service.ops.talks import list_talks

        rows = _run(
            list_talks(db_path=db, owner_discord_user_id=owner_discord_user_id, limit=limit)
        )
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(_JsonResult(ok=True, data={"talks": [asdict(row) for row in rows]}))
        return
    if not rows:
        console.print("No talks found.")
        return
    for row in rows:
        title = " + ".join(row.participant_names)
        console.print(f"- {title} ({row.status}): {row.thread_url()}")


@talks_app.command("close")
def talks_close(
    thread_id: str = typer.Option(..., "--thread-id"),
    db: str | None = typer.Option(None, "--db"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Mark a talk thread as closed in SQLite (does not delete the Discord thread)."""
    try:
        from discord_service.ops.talks import close_talk_by_thread_id

        ok = _run(close_talk_by_thread_id(db_path=db, thread_id=thread_id))
    except Exception as exc:
        if json_:
            _print_json(_JsonResult(ok=False, error=str(exc)))
        raise typer.Exit(code=1) from exc
    if json_:
        _print_json(_JsonResult(ok=True, data={"closed": bool(ok), "thread_id": thread_id}))
    else:
        if ok:
            console.print(f"Closed talk for thread `{thread_id}`.")
        else:
            console.print(f"No open talk found for thread `{thread_id}`.")


def main() -> None:
    app()
