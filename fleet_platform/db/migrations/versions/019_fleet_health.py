"""Create node_health_snapshots table

Revision ID: 019
Revises: 018
Create Date: 2026-05-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_health_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("minion_id", sa.String(255), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("disk_root_used_gb", sa.Numeric(10, 2), nullable=True),
        sa.Column("disk_root_total_gb", sa.Numeric(10, 2), nullable=True),
        sa.Column("disk_root_pct", sa.SmallInteger, nullable=True),
        sa.Column("disk_root_inodes_pct", sa.SmallInteger, nullable=True),
        sa.Column("mem_total_gb", sa.Numeric(8, 2), nullable=True),
        sa.Column("mem_available_gb", sa.Numeric(8, 2), nullable=True),
        sa.Column("mem_used_pct", sa.SmallInteger, nullable=True),
        sa.Column("cpu_load_1m", sa.Numeric(6, 2), nullable=True),
        sa.Column("cpu_load_5m", sa.Numeric(6, 2), nullable=True),
        sa.Column("cpu_load_15m", sa.Numeric(6, 2), nullable=True),
        sa.Column("uptime_seconds", sa.Integer, nullable=True),
        sa.Column("gpu_name", sa.String(255), nullable=True),
        sa.Column("gpu_vram_mb", sa.Integer, nullable=True),
        sa.Column("cpu_power_mw", sa.Integer, nullable=True),
        sa.Column("gpu_power_mw", sa.Integer, nullable=True),
        sa.Column("thermal_pressure", sa.String(20), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_node_health_node_collected",
        "node_health_snapshots",
        ["node_id", "collected_at"],
    )


def downgrade() -> None:
    op.drop_table("node_health_snapshots")
