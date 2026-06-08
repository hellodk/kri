"""Process telemetry pipeline: node_process_stats hypertable (#598, EPIC #597).

Per-process CPU/mem/io samples from the psutil node agent. Stored as a
TimescaleDB hypertable on collected_at with 7-day compression and 14-day
retention (live tables, not long-term trends — those ride Prometheus).

Revision ID: 047
Revises: 046

#571 guard: revision/down_revision MUST be module-level literals (below), not
only in this docstring, or alembic cannot locate the migration and the chain
silently dies at the previous head.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # TimescaleDB requires every unique constraint (incl. the PK) to include the
    # partition column, so create the table with a composite PK (id, collected_at)
    # from the start rather than dropping/recreating it like migration 024 did.
    op.create_table(
        "node_process_stats",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("node_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cmdline", sa.Text(), nullable=True),
        sa.Column("cpu_pct", sa.Float(), nullable=False),
        sa.Column("mem_rss_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mem_pct", sa.Float(), nullable=False),
        sa.Column("num_threads", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("io_read_bytes", sa.BigInteger(), nullable=True),
        sa.Column("io_write_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_llm", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "collected_at"),
    )
    op.create_index(
        "idx_node_process_node_collected",
        "node_process_stats",
        ["node_id", "collected_at"],
    )

    # Convert to a TimescaleDB hypertable partitioned on collected_at.
    op.execute(
        "SELECT create_hypertable('node_process_stats', by_range('collected_at', INTERVAL '1 day'))"
    )
    # Enable compression before adding the policy (required in TimescaleDB 2.x+).
    op.execute(
        "ALTER TABLE node_process_stats SET "
        "(timescaledb.compress = true, timescaledb.compress_orderby = 'collected_at DESC')"
    )
    op.execute("SELECT add_compression_policy('node_process_stats', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('node_process_stats', INTERVAL '14 days')")


def downgrade() -> None:
    # Drop policies first; dropping the table removes the hypertable too.
    op.execute("SELECT remove_retention_policy('node_process_stats', true)")
    op.execute("SELECT remove_compression_policy('node_process_stats', true)")
    op.drop_index("idx_node_process_node_collected", table_name="node_process_stats")
    op.drop_table("node_process_stats")
