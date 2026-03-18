from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import typer
from bt_store.engine import init_database, resolve_database_path
from discord_service.config import load_runtime_config as load_discord_config
from discord_service.ops import seed_agent
from discord_service.ops.feed import (
    publish_pending_feeds_once,
    republish_source_by_video,
    retry_failed_posts_by_video,
    source_feed_status_by_video,
)
from discord_service.ops.talks import close_talk_by_thread_id, list_talks
from memory_service.api.entrypoint import run_memories_api
from memory_service.entrypoint import run_collector
from memory_service.ops import request_manual_ingest
from rich.console import Console
from rich.table import Table

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
    try:
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
