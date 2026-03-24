"""Scope platform_routes uniqueness by container.

Revision ID: 0002_platform_routes_voice_scope
Revises: 0001_initial_schema
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op

revision = "0002_platform_routes_voice_scope"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _dedupe_by_unique_key(partition_sql: str) -> None:
    op.execute(
        f"""
        DELETE FROM platform_routes
        WHERE route_id IN (
            SELECT route_id FROM (
                SELECT
                    route_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY {partition_sql}
                        ORDER BY created_at DESC, route_id DESC
                    ) AS row_num
                FROM platform_routes
            ) ranked
            WHERE ranked.row_num > 1
        )
        """
    )


def upgrade() -> None:
    _dedupe_by_unique_key("platform, purpose, agent_id, container_id")
    with op.batch_alter_table("platform_routes", schema=None) as batch_op:
        batch_op.drop_constraint("uq_platform_routes_platform", type_="unique")
        batch_op.create_unique_constraint(
            "uq_platform_routes_platform_purpose_agent_container",
            ["platform", "purpose", "agent_id", "container_id"],
        )


def downgrade() -> None:
    _dedupe_by_unique_key("platform, purpose, agent_id")
    with op.batch_alter_table("platform_routes", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_platform_routes_platform_purpose_agent_container", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_platform_routes_platform",
            ["platform", "purpose", "agent_id"],
        )
