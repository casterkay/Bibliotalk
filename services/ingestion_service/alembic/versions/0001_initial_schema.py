"""Initial evidence store schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-07 00:00:00
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
        "figures",
        sa.Column("figure_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("emos_user_id", sa.String(length=100), nullable=False),
        sa.Column("persona_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("figure_id"),
        sa.UniqueConstraint("emos_user_id"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("figure_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("subscription_type", sa.String(length=20), nullable=False),
        sa.Column("subscription_url", sa.Text(), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["figure_id"], ["figures.figure_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("subscription_id"),
    )
    op.create_index("ix_subscriptions_figure_id", "subscriptions", ["figure_id"])
    op.create_table(
        "sources",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("figure_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("group_id", sa.String(length=300), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("channel_name", sa.String(length=300), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_meta_json", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(length=20), nullable=False),
        sa.Column("manual_ingestion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["figure_id"], ["figures.figure_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("figure_id", "platform", "external_id", name="uq_source_identity"),
    )
    op.create_index("ix_sources_figure_id", "sources", ["figure_id"])
    op.create_index("ix_sources_group_id", "sources", ["group_id"])
    op.create_table(
        "segments",
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("create_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_superseded", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("segment_id"),
        sa.UniqueConstraint("source_id", "seq", "sha256", name="uq_segment_dedup"),
    )
    op.create_index("ix_segments_source_id", "segments", ["source_id"])
    op.create_table(
        "transcript_batches",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("speaker_label", sa.String(length=200), nullable=True),
        sa.Column("start_seq", sa.Integer(), nullable=False),
        sa.Column("end_seq", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("batch_rule", sa.String(length=30), nullable=False),
        sa.Column("posted_to_discord", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index("ix_transcript_batches_source_id", "transcript_batches", ["source_id"])
    op.create_index(
        "ix_transcript_batches_unposted", "transcript_batches", ["source_id", "posted_to_discord"]
    )
    op.create_table(
        "ingest_state",
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("last_seen_video_id", sa.String(length=200), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.subscription_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("subscription_id"),
    )
    op.create_table(
        "discord_map",
        sa.Column("figure_id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.String(length=30), nullable=False),
        sa.Column("channel_id", sa.String(length=30), nullable=False),
        sa.Column("bot_application_id", sa.String(length=30), nullable=True),
        sa.Column("bot_user_id", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["figure_id"], ["figures.figure_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("figure_id"),
    )
    op.create_table(
        "discord_posts",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("figure_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("parent_message_id", sa.String(length=30), nullable=True),
        sa.Column("thread_id", sa.String(length=30), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["transcript_batches.batch_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["figure_id"], ["figures.figure_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
        sa.UniqueConstraint("source_id", "batch_id", name="uq_discord_post_dedup"),
    )
    op.create_index("ix_discord_posts_source_id", "discord_posts", ["source_id"])
    op.create_index("ix_discord_posts_pending", "discord_posts", ["figure_id", "post_status"])


def downgrade() -> None:
    op.drop_index("ix_discord_posts_pending", table_name="discord_posts")
    op.drop_index("ix_discord_posts_source_id", table_name="discord_posts")
    op.drop_table("discord_posts")
    op.drop_table("discord_map")
    op.drop_table("ingest_state")
    op.drop_index("ix_transcript_batches_unposted", table_name="transcript_batches")
    op.drop_index("ix_transcript_batches_source_id", table_name="transcript_batches")
    op.drop_table("transcript_batches")
    op.drop_index("ix_segments_source_id", table_name="segments")
    op.drop_table("segments")
    op.drop_index("ix_sources_group_id", table_name="sources")
    op.drop_index("ix_sources_figure_id", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_subscriptions_figure_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("figures")
