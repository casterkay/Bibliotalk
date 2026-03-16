"""Initial bt_store schema (integrated).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("persona_summary", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_agents_is_active"), "agents", ["is_active"], unique=False)
    op.create_index(op.f("ix_agents_kind"), "agents", ["kind"], unique=False)
    op.create_index(op.f("ix_agents_slug"), "agents", ["slug"], unique=False)

    op.create_table(
        "agent_platform_identities",
        sa.Column("identity_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("platform_user_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("platform", "platform_user_id"),
        sa.UniqueConstraint("agent_id", "platform"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.agent_id"],
            name=op.f("fk_agent_platform_identities_agent_id_agents"),
        ),
    )
    op.create_index(
        op.f("ix_agent_platform_identities_agent_id"),
        "agent_platform_identities",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_platform_identities_platform"),
        "agent_platform_identities",
        ["platform"],
        unique=False,
    )

    op.create_table(
        "rooms",
        sa.Column("room_pk", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("platform", "room_id"),
    )
    op.create_index(op.f("ix_rooms_kind"), "rooms", ["kind"], unique=False)
    op.create_index(op.f("ix_rooms_platform"), "rooms", ["platform"], unique=False)

    op.create_table(
        "room_members",
        sa.Column("member_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("room_pk", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("platform_user_id", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("member_kind", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("room_pk", "platform_user_id"),
        sa.ForeignKeyConstraint(
            ["room_pk"], ["rooms.room_pk"], name=op.f("fk_room_members_room_pk_rooms")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.agent_id"], name=op.f("fk_room_members_agent_id_agents")
        ),
    )
    op.create_index(op.f("ix_room_members_agent_id"), "room_members", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_room_members_member_kind"), "room_members", ["member_kind"], unique=False
    )
    op.create_index(op.f("ix_room_members_platform"), "room_members", ["platform"], unique=False)
    op.create_index(op.f("ix_room_members_room_pk"), "room_members", ["room_pk"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("subscription_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("content_platform", sa.String(length=64), nullable=False),
        sa.Column("subscription_type", sa.String(length=32), nullable=False),
        sa.Column("subscription_url", sa.Text(), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.agent_id"], name=op.f("fk_subscriptions_agent_id_agents")
        ),
        sa.UniqueConstraint(
            "agent_id",
            "content_platform",
            "subscription_type",
            "subscription_url",
            name="uq_subscriptions_identity",
        ),
    )
    op.create_index(op.f("ix_subscriptions_agent_id"), "subscriptions", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_subscriptions_content_platform"),
        "subscriptions",
        ["content_platform"],
        unique=False,
    )
    op.create_index(
        op.f("ix_subscriptions_is_active"), "subscriptions", ["is_active"], unique=False
    )

    op.create_table(
        "subscription_state",
        sa.Column("subscription_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("last_seen_external_id", sa.String(length=255), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.subscription_id"],
            name=op.f("fk_subscription_state_subscription_id_subscriptions"),
        ),
    )

    op.create_table(
        "sources",
        sa.Column("source_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("content_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("author", sa.String(length=512), nullable=True),
        sa.Column("channel_name", sa.String(length=512), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_meta_json", sa.JSON(), nullable=True),
        sa.Column("emos_group_id", sa.String(length=255), nullable=False),
        sa.Column("meta_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.agent_id"], name=op.f("fk_sources_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.subscription_id"],
            name=op.f("fk_sources_subscription_id_subscriptions"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("agent_id", "content_platform", "external_id"),
    )
    op.create_index(op.f("ix_sources_agent_id"), "sources", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_sources_content_platform"), "sources", ["content_platform"], unique=False
    )
    op.create_index(op.f("ix_sources_emos_group_id"), "sources", ["emos_group_id"], unique=False)
    op.create_index(
        op.f("ix_sources_subscription_id"), "sources", ["subscription_id"], unique=False
    )

    op.create_table(
        "source_ingestion_state",
        sa.Column("source_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("ingest_status", sa.String(length=32), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.String(length=120), nullable=True),
        sa.Column("manual_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.source_id"],
            name=op.f("fk_source_ingestion_state_source_id_sources"),
        ),
    )
    op.create_index(
        op.f("ix_source_ingestion_state_ingest_status"),
        "source_ingestion_state",
        ["ingest_status"],
        unique=False,
    )

    op.create_table(
        "segments",
        sa.Column("segment_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("emos_message_id", sa.String(length=255), nullable=False),
        sa.Column("create_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_superseded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.source_id"],
            name=op.f("fk_segments_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.agent_id"],
            name=op.f("fk_segments_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "seq", "sha256"),
    )
    op.create_index(op.f("ix_segments_agent_id"), "segments", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_segments_emos_message_id"), "segments", ["emos_message_id"], unique=False
    )
    op.create_index(op.f("ix_segments_is_superseded"), "segments", ["is_superseded"], unique=False)
    op.create_index(op.f("ix_segments_source_id"), "segments", ["source_id"], unique=False)
    op.create_index(
        "ix_segments_agent_source_seq",
        "segments",
        ["agent_id", "source_id", "seq"],
        unique=False,
    )

    op.create_table(
        "source_text_batches",
        sa.Column("batch_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("speaker_label", sa.String(length=200), nullable=True),
        sa.Column("start_seq", sa.Integer(), nullable=False),
        sa.Column("end_seq", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("batch_rule", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.source_id"],
            name=op.f("fk_source_text_batches_source_id_sources"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_source_text_batches_kind"), "source_text_batches", ["kind"], unique=False
    )
    op.create_index(
        op.f("ix_source_text_batches_source_id"), "source_text_batches", ["source_id"], unique=False
    )

    op.create_table(
        "talk_threads",
        sa.Column("thread_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=255), nullable=False),
        sa.Column("sender_agent_id", sa.Uuid(), nullable=True),
        sa.Column("sender_platform_user_id", sa.String(length=255), nullable=False),
        sa.Column("platform_event_id", sa.String(length=255), nullable=True),
        sa.Column("modality", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["sender_agent_id"],
            ["agents.agent_id"],
            name=op.f("fk_talk_threads_sender_agent_id_agents"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_talk_threads_modality"), "talk_threads", ["modality"], unique=False)
    op.create_index(op.f("ix_talk_threads_platform"), "talk_threads", ["platform"], unique=False)
    op.create_index(op.f("ix_talk_threads_room_id"), "talk_threads", ["room_id"], unique=False)

    op.create_table(
        "platform_routes",
        sa.Column("route_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("container_id", sa.String(length=255), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.agent_id"], name=op.f("fk_platform_routes_agent_id_agents")
        ),
        sa.UniqueConstraint("platform", "purpose", "agent_id"),
    )
    op.create_index(
        op.f("ix_platform_routes_platform"), "platform_routes", ["platform"], unique=False
    )
    op.create_index(
        op.f("ix_platform_routes_purpose"), "platform_routes", ["purpose"], unique=False
    )
    op.create_index(
        op.f("ix_platform_routes_agent_id"), "platform_routes", ["agent_id"], unique=False
    )

    op.create_table(
        "platform_posts",
        sa.Column("post_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("container_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("platform_event_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.agent_id"], name=op.f("fk_platform_posts_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.source_id"], name=op.f("fk_platform_posts_source_id_sources")
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.segment_id"],
            name=op.f("fk_platform_posts_segment_id_segments"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["source_text_batches.batch_id"],
            name=op.f("fk_platform_posts_batch_id_source_text_batches"),
        ),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_platform_posts_agent_id"), "platform_posts", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_posts_batch_id"), "platform_posts", ["batch_id"], unique=False
    )
    op.create_index(op.f("ix_platform_posts_kind"), "platform_posts", ["kind"], unique=False)
    op.create_index(
        op.f("ix_platform_posts_platform"), "platform_posts", ["platform"], unique=False
    )
    op.create_index(
        op.f("ix_platform_posts_container_id"), "platform_posts", ["container_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_posts_segment_id"), "platform_posts", ["segment_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_posts_source_id"), "platform_posts", ["source_id"], unique=False
    )
    op.create_index(op.f("ix_platform_posts_status"), "platform_posts", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("platform_posts")
    op.drop_table("platform_routes")
    op.drop_table("talk_threads")
    op.drop_table("source_text_batches")
    op.drop_index("ix_segments_agent_source_seq", table_name="segments")
    op.drop_table("segments")
    op.drop_table("source_ingestion_state")
    op.drop_table("sources")
    op.drop_table("subscription_state")
    op.drop_table("subscriptions")
    op.drop_table("room_members")
    op.drop_table("rooms")
    op.drop_table("agent_platform_identities")
    op.drop_table("agents")
