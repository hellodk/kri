"""Create node_process_stats hypertable

Revision ID: 047
Revises: 046
Create Date: 2026-06-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_process_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("minion_id", sa.String(255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cmdline", sa.Text(), nullable=True),
        sa.Column("cpu_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("mem_rss_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mem_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("num_threads", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("io_read_bytes", sa.BigInteger(), nullable=True),
        sa.Column("io_write_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_llm", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "collected_at"),
    )
    op.create_index(
        "idx_node_process_node_collected",
        "node_process_stats",
        ["node_id", "collected_at"],
    )
    op.execute(
        "SELECT create_hypertable('node_process_stats', by_range('collected_at', INTERVAL '1 day'), migrate_data => true)"
    )
    op.execute(
        "ALTER TABLE node_process_stats SET (timescaledb.compress = true, timescaledb.compress_orderby = 'collected_at DESC')"
    )
    op.execute("SELECT add_compression_policy('node_process_stats', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('node_process_stats', INTERVAL '14 days')")


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('node_process_stats', true)")
    op.execute("SELECT remove_compression_policy('node_process_stats', true)")
    op.drop_table("node_process_stats")
