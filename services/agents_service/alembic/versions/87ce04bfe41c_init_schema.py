"""init schema

Revision ID: 87ce04bfe41c
Revises: 20260306_0001
Create Date: 2026-03-06 14:55:08.781434

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "87ce04bfe41c"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("matrix_user_id", sa.String(length=256), nullable=False, unique=True),
        sa.Column("persona_prompt", sa.Text(), nullable=False),
        sa.Column(
            "llm_model",
            sa.String(length=128),
            nullable=False,
            server_default="gemini-2.5-flash",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "agent_emos_config",
        sa.Column("agent_id", sa.String(length=36), primary_key=True),
        sa.Column("emos_base_url", sa.String(length=512), nullable=False),
        sa.Column("emos_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("emos_api_key", sa.Text(), nullable=True),
        sa.Column("tenant_prefix", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_prefix", name="uq_agent_emos_config_tenant_prefix"),
    )

    op.create_table(
        "profile_rooms",
        sa.Column("agent_id", sa.String(length=36), primary_key=True),
        sa.Column("matrix_room_id", sa.String(length=256), nullable=False, unique=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("external_url", sa.String(length=1024), nullable=True),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("author", sa.String(length=256), nullable=True),
        sa.Column("published_at", sa.String(length=64), nullable=True),
        sa.Column(
            "raw_meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("emos_group_id", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("emos_group_id", name="uq_sources_emos_group_id"),
    )
    op.create_index("ix_sources_agent_id", "sources", ["agent_id"], unique=False)

    op.create_table(
        "segments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("speaker", sa.String(length=256), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("emos_message_id", sa.String(length=512), nullable=False),
        sa.Column("source_title", sa.String(length=1024), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("matrix_event_id", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("emos_message_id", name="uq_segments_emos_message_id"),
    )
    op.create_index("ix_segments_agent_id", "segments", ["agent_id"], unique=False)
    op.create_index("ix_segments_source_id", "segments", ["source_id"], unique=False)
    op.create_index("ix_segments_seq", "segments", ["seq"], unique=False)

    op.create_table(
        "chat_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("matrix_room_id", sa.String(length=256), nullable=False),
        sa.Column("sender_agent_id", sa.String(length=36), nullable=True),
        sa.Column("sender_matrix_user_id", sa.String(length=256), nullable=False),
        sa.Column("matrix_event_id", sa.String(length=256), nullable=True),
        sa.Column("modality", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_chat_history_matrix_room_id",
        "chat_history",
        ["matrix_room_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_history_sender_agent_id",
        "chat_history",
        ["sender_agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_history_sender_agent_id", table_name="chat_history")
    op.drop_index("ix_chat_history_matrix_room_id", table_name="chat_history")
    op.drop_table("chat_history")

    op.drop_index("ix_segments_seq", table_name="segments")
    op.drop_index("ix_segments_source_id", table_name="segments")
    op.drop_index("ix_segments_agent_id", table_name="segments")
    op.drop_table("segments")

    op.drop_index("ix_sources_agent_id", table_name="sources")
    op.drop_table("sources")

    op.drop_table("profile_rooms")
    op.drop_table("agent_emos_config")
    op.drop_table("agents")
