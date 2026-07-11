"""Add fleet_recommendations table for fleet-wide AI recommendations (#4).

Revision ID: 064
Revises: 063
Create Date: 2026-07-11

Replaces the per-node "Ask AI" quick-fix (#294, removed in this same change)
with a fleet-wide, LLM-generated recommendation feed. A row is written each
time recommendations are (re)generated — either by the daily Celery beat
schedule (``generated_by="schedule"``) or on-demand by an operator
(``generated_by=<email>``). The UI reads only the newest row; history is kept
for audit/trend purposes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fleet_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("generated_by", sa.String(255), nullable=True),
    )
    op.create_index(
        "idx_fleet_recommendations_generated_at",
        "fleet_recommendations",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_fleet_recommendations_generated_at", table_name="fleet_recommendations")
    op.drop_table("fleet_recommendations")
