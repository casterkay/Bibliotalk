from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from bt_store.engine import get_session_factory, init_database, resolve_database_path
from bt_store.models_core import Agent, Room, RoomMember
from bt_store.models_evidence import Segment, Source
from bt_store.models_ingestion import (
    SourceIngestionState,
    SourceTextBatch,
    Subscription,
    SubscriptionState,
)
from bt_store.models_runtime import (
    PlatformPost,
    PlatformRoute,
    PlatformUserSettings,
)
from sqlalchemy import select


def _parse_uuid(value: Any) -> uuid.UUID:
    if value is None:
        raise ValueError("missing uuid value")
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, bytes):
        if len(value) == 16:
            return uuid.UUID(bytes=value)
        value = value.decode("utf-8")
    if isinstance(value, str):
        return uuid.UUID(value)
    raise TypeError(f"Unsupported uuid type: {type(value)}")


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        raw = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _parse_json_blob(value: Any) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    return {"raw": str(value)}


@dataclass(frozen=True, slots=True)
class LegacyRowCounts:
    figures: int = 0
    subscriptions: int = 0
    ingest_state: int = 0
    sources: int = 0
    segments: int = 0
    transcript_batches: int = 0
    discord_map: int = 0
    discord_posts: int = 0
    discord_user_settings: int = 0
    talk_threads: int = 0
    talk_participants: int = 0


class LegacyReader:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def _table_exists(self, table: str) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        return row is not None

    def counts(self) -> LegacyRowCounts:
        def _count(table: str) -> int:
            if not self._table_exists(table):
                return 0
            return int(
                self._conn.execute(f"SELECT COUNT(1) AS n FROM {table}").fetchone()["n"]
            )

        return LegacyRowCounts(
            figures=_count("figures"),
            subscriptions=_count("subscriptions"),
            ingest_state=_count("ingest_state"),
            sources=_count("sources"),
            segments=_count("segments"),
            transcript_batches=_count("transcript_batches"),
            discord_map=_count("discord_map"),
            discord_posts=_count("discord_posts"),
            discord_user_settings=_count("discord_user_settings"),
            talk_threads=_count("talk_threads"),
            talk_participants=_count("talk_participants"),
        )

    def iter_rows(self, table: str) -> Iterable[sqlite3.Row]:
        if not self._table_exists(table):
            return []
        return self._conn.execute(f"SELECT * FROM {table}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-shot backfill: legacy bt_common.evidence_store SQLite → bt_store SQLite.",
    )
    parser.add_argument(
        "--legacy-db",
        required=True,
        help="Path to legacy SQLite DB (bt_common.evidence_store schema).",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Target SQLite path (bt_store schema). Defaults to BIBLIOTALK_DB_PATH / ~/.bibliotalk/bibliotalk.db.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write into the target DB (default is plan-only, no writes).",
    )
    parser.add_argument(
        "--allow-same-path",
        action="store_true",
        help="Allow legacy and target to be the same path (dangerous; only safe if legacy tables are already gone).",
    )
    return parser


async def _migrate(*, legacy_path: Path, target_db_path: Path) -> dict[str, int]:
    now = datetime.now(UTC)
    legacy = LegacyReader(legacy_path)
    try:
        await init_database(target_db_path)
        session_factory = get_session_factory(target_db_path)

        agents_by_id: dict[uuid.UUID, dict[str, Any]] = {}
        discord_channel_by_agent_id: dict[uuid.UUID, str] = {}
        batches_by_id: dict[uuid.UUID, dict[str, Any]] = {}
        sources_by_id: dict[uuid.UUID, dict[str, Any]] = {}

        counts: dict[str, int] = {
            "agents": 0,
            "subscriptions": 0,
            "subscription_state": 0,
            "sources": 0,
            "source_ingestion_state": 0,
            "segments": 0,
            "source_text_batches": 0,
            "platform_routes": 0,
            "platform_posts": 0,
            "platform_user_settings": 0,
            "rooms": 0,
            "room_members": 0,
        }

        async with session_factory() as session:
            for row in legacy.iter_rows("figures"):
                agent_id = _parse_uuid(row["figure_id"])
                slug = str(row["emos_user_id"] or "").strip()
                if not slug:
                    continue
                display_name = str(row["display_name"] or "").strip() or slug
                persona_summary = row["persona_summary"] or None
                status = str(row["status"] or "active").strip().lower()
                is_active = status in {"active", "enabled", "open", "ok", "1", "true"}

                agents_by_id[agent_id] = {"slug": slug, "display_name": display_name}

                existing = await session.get(Agent, agent_id)
                if existing is not None:
                    continue
                session.add(
                    Agent(
                        agent_id=agent_id,
                        kind="figure",
                        slug=slug,
                        display_name=display_name,
                        persona_summary=(
                            str(persona_summary).strip() if persona_summary else None
                        ),
                        is_active=is_active,
                        created_at=now,
                    )
                )
                counts["agents"] += 1
            await session.commit()

            for row in legacy.iter_rows("subscriptions"):
                subscription_id = _parse_uuid(row["subscription_id"])
                agent_id = _parse_uuid(row["figure_id"])
                platform = str(row["platform"] or "youtube").strip()
                raw_type = str(row["subscription_type"] or "").strip()
                subscription_type = (
                    raw_type if "." in raw_type else f"{platform}.{raw_type}"
                )

                existing = await session.get(Subscription, subscription_id)
                if existing is not None:
                    continue
                session.add(
                    Subscription(
                        subscription_id=subscription_id,
                        agent_id=agent_id,
                        content_platform=platform,
                        subscription_type=subscription_type,
                        subscription_url=str(row["subscription_url"] or ""),
                        poll_interval_minutes=int(row["poll_interval_minutes"] or 30),
                        is_active=bool(row["is_active"]),
                        created_at=now,
                    )
                )
                counts["subscriptions"] += 1
            await session.commit()

            for row in legacy.iter_rows("ingest_state"):
                subscription_id = _parse_uuid(row["subscription_id"])
                existing = await session.get(SubscriptionState, subscription_id)
                if existing is not None:
                    continue
                session.add(
                    SubscriptionState(
                        subscription_id=subscription_id,
                        last_seen_external_id=(
                            str(row["last_seen_video_id"])
                            if row["last_seen_video_id"]
                            else None
                        ),
                        last_published_at=_parse_dt(row["last_published_at"]),
                        last_polled_at=_parse_dt(row["last_polled_at"]),
                        failure_count=int(row["failure_count"] or 0),
                        next_retry_at=_parse_dt(row["next_retry_at"]),
                        updated_at=now,
                    )
                )
                counts["subscription_state"] += 1
            await session.commit()

            for row in legacy.iter_rows("sources"):
                source_id = _parse_uuid(row["source_id"])
                agent_id = _parse_uuid(row["figure_id"])
                platform = str(row["platform"] or "youtube").strip()
                external_id = str(row["external_id"] or "").strip()
                group_id = (
                    str(row["group_id"] or "").strip()
                    or f"{agents_by_id.get(agent_id, {}).get('slug', 'unknown')}:{platform}:{external_id}"
                )

                sources_by_id[source_id] = {
                    "group_id": group_id,
                    "agent_id": agent_id,
                }

                existing = await session.get(Source, source_id)
                if existing is None:
                    session.add(
                        Source(
                            source_id=source_id,
                            agent_id=agent_id,
                            subscription_id=_parse_uuid(row["subscription_id"])
                            if row["subscription_id"]
                            else None,
                            content_platform=platform,
                            external_id=external_id,
                            external_url=str(row["source_url"] or "").strip() or None,
                            title=str(row["title"] or "").strip()
                            or external_id
                            or group_id,
                            author=None,
                            channel_name=(
                                str(row["channel_name"]).strip()
                                if row["channel_name"]
                                else None
                            ),
                            published_at=_parse_dt(row["published_at"]),
                            raw_meta_json=_parse_json_blob(row["raw_meta_json"]),
                            emos_group_id=group_id,
                            meta_synced_at=_parse_dt(row["source_meta_synced_at"]),
                            created_at=now,
                        )
                    )
                    counts["sources"] += 1

                state = await session.get(SourceIngestionState, source_id)
                if state is None:
                    state = SourceIngestionState(source_id=source_id)
                    session.add(state)
                    counts["source_ingestion_state"] += 1
                state.ingest_status = str(row["transcript_status"] or "pending").strip()
                state.failure_count = int(row["transcript_failure_count"] or 0)
                state.last_attempt_at = _parse_dt(row["transcript_last_attempt_at"])
                state.next_retry_at = _parse_dt(row["transcript_next_retry_at"])
                state.skip_reason = (
                    str(row["transcript_skip_reason"]).strip()
                    if row["transcript_skip_reason"]
                    else None
                )
                state.manual_requested_at = _parse_dt(
                    row["manual_ingestion_requested_at"]
                )
                state.updated_at = now

            await session.commit()

            for row in legacy.iter_rows("segments"):
                segment_id = _parse_uuid(row["segment_id"])
                source_id = _parse_uuid(row["source_id"])
                seq = int(row["seq"] or 0)
                sha256 = str(row["sha256"] or "")

                source_info = sources_by_id.get(source_id) or {}
                group_id = str(source_info.get("group_id") or "")
                agent_id = (
                    _parse_uuid(source_info["agent_id"])
                    if source_info.get("agent_id")
                    else uuid.UUID(int=0)
                )

                existing = await session.get(Segment, segment_id)
                if existing is not None:
                    continue
                session.add(
                    Segment(
                        segment_id=segment_id,
                        source_id=source_id,
                        agent_id=agent_id,
                        seq=seq,
                        text=str(row["text"] or ""),
                        sha256=sha256,
                        speaker=None,
                        start_ms=int(row["start_ms"])
                        if row["start_ms"] is not None
                        else None,
                        end_ms=int(row["end_ms"])
                        if row["end_ms"] is not None
                        else None,
                        emos_message_id=f"{group_id}:seg:{seq}"
                        if group_id
                        else f"legacy:seg:{segment_id}",
                        create_time=_parse_dt(row["create_time"]),
                        is_superseded=bool(row["is_superseded"]),
                        created_at=now,
                    )
                )
                counts["segments"] += 1
            await session.commit()

            for row in legacy.iter_rows("transcript_batches"):
                batch_id = _parse_uuid(row["batch_id"])
                batches_by_id[batch_id] = {
                    "start_seq": int(row["start_seq"] or 0),
                    "end_seq": int(row["end_seq"] or 0),
                    "text": str(row["text"] or ""),
                }
                existing = await session.get(SourceTextBatch, batch_id)
                if existing is not None:
                    continue
                session.add(
                    SourceTextBatch(
                        batch_id=batch_id,
                        source_id=_parse_uuid(row["source_id"]),
                        kind="transcript",
                        speaker_label=str(row["speaker_label"]).strip()
                        if row["speaker_label"]
                        else None,
                        start_seq=int(row["start_seq"] or 0),
                        end_seq=int(row["end_seq"] or 0),
                        start_ms=int(row["start_ms"])
                        if row["start_ms"] is not None
                        else None,
                        end_ms=int(row["end_ms"])
                        if row["end_ms"] is not None
                        else None,
                        text=str(row["text"] or ""),
                        batch_rule=str(row["batch_rule"] or "legacy"),
                        created_at=now,
                    )
                )
                counts["source_text_batches"] += 1
            await session.commit()

            for row in legacy.iter_rows("discord_map"):
                agent_id = _parse_uuid(row["figure_id"])
                channel_id = str(row["channel_id"] or "").strip()
                if channel_id:
                    discord_channel_by_agent_id[agent_id] = channel_id

                existing_route = (
                    await session.execute(
                        select(PlatformRoute.route_id).where(
                            PlatformRoute.platform == "discord",
                            PlatformRoute.purpose == "feed",
                            PlatformRoute.agent_id == agent_id,
                        )
                    )
                ).first()
                if existing_route is not None:
                    continue

                session.add(
                    PlatformRoute(
                        route_id=uuid.uuid4(),
                        platform="discord",
                        purpose="feed",
                        agent_id=agent_id,
                        container_id=channel_id,
                        config_json={
                            "guild_id": str(row["guild_id"] or "").strip(),
                            "bot_application_id": (
                                str(row["bot_application_id"]).strip()
                                if row["bot_application_id"]
                                else None
                            ),
                            "bot_user_id": (
                                str(row["bot_user_id"]).strip()
                                if row["bot_user_id"]
                                else None
                            ),
                        },
                        created_at=now,
                    )
                )
                counts["platform_routes"] += 1
            await session.commit()

            for row in legacy.iter_rows("discord_user_settings"):
                platform_user_id = str(row["discord_user_id"] or "").strip()
                if not platform_user_id:
                    continue
                pk = {"platform": "discord", "platform_user_id": platform_user_id}
                existing = await session.get(PlatformUserSettings, pk)
                if existing is not None:
                    continue
                session.add(
                    PlatformUserSettings(
                        platform="discord",
                        platform_user_id=platform_user_id,
                        config_json={
                            "default_guild_id": str(row["default_guild_id"]).strip()
                            if row["default_guild_id"]
                            else None
                        },
                        created_at=_parse_dt(row["created_at"]) or now,
                        updated_at=_parse_dt(row["updated_at"]) or now,
                    )
                )
                counts["platform_user_settings"] += 1
            await session.commit()

            for row in legacy.iter_rows("discord_posts"):
                post_id = _parse_uuid(row["post_id"])
                existing = await session.get(PlatformPost, post_id)
                if existing is not None:
                    continue

                agent_id = _parse_uuid(row["figure_id"])
                source_id = _parse_uuid(row["source_id"])
                batch_id = _parse_uuid(row["batch_id"]) if row["batch_id"] else None
                posted_at = _parse_dt(row["posted_at"]) or now

                channel_id = discord_channel_by_agent_id.get(agent_id, "")
                thread_id = str(row["thread_id"]).strip() if row["thread_id"] else None

                if batch_id is None:
                    kind = "feed.parent"
                    idempotency_key = f"discord:feed:source:{source_id}:parent"
                    platform_event_id = (
                        str(row["parent_message_id"]).strip()
                        if row["parent_message_id"]
                        else None
                    )
                else:
                    kind = "feed.batch"
                    batch = batches_by_id.get(batch_id)
                    if batch is None:
                        idempotency_key = f"legacy:discord_post:{post_id}"
                    else:
                        text_fingerprint = hashlib.sha256(
                            (batch["text"] or "").encode("utf-8")
                        ).hexdigest()[:16]
                        idempotency_key = f"discord:feed:source:{source_id}:batch:{batch['start_seq']}:{batch['end_seq']}:{text_fingerprint}"
                    platform_event_id = None

                session.add(
                    PlatformPost(
                        post_id=post_id,
                        platform="discord",
                        kind=kind,
                        agent_id=agent_id,
                        container_id=channel_id,
                        thread_id=thread_id,
                        source_id=source_id,
                        segment_id=None,
                        batch_id=batch_id,
                        idempotency_key=idempotency_key,
                        platform_event_id=platform_event_id,
                        status=str(row["post_status"] or "pending").strip(),
                        error=None,
                        meta_json={
                            "legacy_parent_message_id": str(
                                row["parent_message_id"]
                            ).strip()
                            if row["parent_message_id"]
                            else None
                        },
                        created_at=posted_at,
                        updated_at=posted_at,
                    )
                )
                counts["platform_posts"] += 1
            await session.commit()

            for row in legacy.iter_rows("talk_threads"):
                talk_id = _parse_uuid(row["talk_id"])
                existing = await session.get(Room, talk_id)
                if existing is not None:
                    continue

                meta: dict[str, Any] = {
                    "guild_id": str(row["guild_id"] or "").strip(),
                    "hub_channel_id": str(row["hub_channel_id"] or "").strip(),
                }
                if row["last_routed_figure_id"]:
                    meta["last_routed_agent_id"] = str(
                        _parse_uuid(row["last_routed_figure_id"])
                    )

                room = Room(
                    room_pk=talk_id,
                    platform="discord",
                    room_id=str(row["thread_id"] or "").strip(),
                    kind="dialogue",
                    status=str(row["status"] or "open").strip(),
                    last_activity_at=_parse_dt(row["last_activity_at"]) or now,
                    meta_json=meta,
                    created_at=_parse_dt(row["created_at"]) or now,
                )
                session.add(room)
                counts["rooms"] += 1

                owner_discord_user_id = str(row["owner_discord_user_id"] or "").strip()
                if owner_discord_user_id:
                    session.add(
                        RoomMember(
                            member_id=uuid.uuid4(),
                            room_pk=room.room_pk,
                            platform="discord",
                            platform_user_id=owner_discord_user_id,
                            agent_id=None,
                            member_kind="human",
                            role="owner",
                            display_order=0,
                            created_at=room.created_at,
                        )
                    )
                    counts["room_members"] += 1
            await session.commit()

            participants_by_talk: dict[uuid.UUID, list[tuple[uuid.UUID, int]]] = {}
            for row in legacy.iter_rows("talk_participants"):
                talk_id = _parse_uuid(row["talk_id"])
                agent_id = _parse_uuid(row["figure_id"])
                display_order = int(row["display_order"] or 0)
                participants_by_talk.setdefault(talk_id, []).append(
                    (agent_id, display_order)
                )

            for talk_id, members in participants_by_talk.items():
                for agent_id, display_order in sorted(members, key=lambda it: it[1]):
                    agent = agents_by_id.get(agent_id)
                    if agent is None:
                        continue
                    platform_user_id = f"agent:{agent['slug']}"
                    existing_member = (
                        await session.execute(
                            select(RoomMember.member_id).where(
                                RoomMember.room_pk == talk_id,
                                RoomMember.platform_user_id == platform_user_id,
                            )
                        )
                    ).first()
                    if existing_member is not None:
                        continue
                    session.add(
                        RoomMember(
                            member_id=uuid.uuid4(),
                            room_pk=talk_id,
                            platform="discord",
                            platform_user_id=platform_user_id,
                            agent_id=agent_id,
                            member_kind="agent",
                            role="participant",
                            display_order=display_order,
                            created_at=now,
                        )
                    )
                    counts["room_members"] += 1

            await session.commit()

        return counts
    finally:
        legacy.close()


def _print_counts(prefix: str, counts: dict[str, int]) -> None:
    items = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"{prefix}{items}")


def main() -> int:
    args = build_parser().parse_args()
    legacy_path = Path(args.legacy_db).expanduser().resolve()
    if not legacy_path.exists():
        raise SystemExit(f"Legacy DB not found: {legacy_path}")

    target_db_path = resolve_database_path(args.db)
    if legacy_path == target_db_path and not args.allow_same_path:
        raise SystemExit(
            "Refusing to backfill into the same path as legacy DB. "
            "Provide a different --db target, or pass --allow-same-path if you know the legacy schema is already gone."
        )

    legacy = LegacyReader(legacy_path)
    try:
        legacy_counts = legacy.counts()
    finally:
        legacy.close()

    print(
        "Legacy rows: "
        + ", ".join(
            f"{k}={getattr(legacy_counts, k)}"
            for k in legacy_counts.__dataclass_fields__
        )
    )
    print(f"Target DB: {target_db_path}")
    if not args.apply:
        print("Plan-only mode (no writes). Re-run with --apply to execute.")
        return 0

    migrated = asyncio.run(
        _migrate(legacy_path=legacy_path, target_db_path=target_db_path)
    )
    _print_counts("Migrated: ", migrated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
