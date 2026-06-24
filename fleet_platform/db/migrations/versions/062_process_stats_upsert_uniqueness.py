"""Add unique constraint to node_process_stats for idempotent ingest (#672).

Revision ID: 062
Revises: 061
Create Date: 2026-06-24

Without a uniqueness guard the ingest endpoint inserts duplicate rows whenever
a Salt minion re-delivers the same process-stats payload (e.g. on retry or
reconnect).  A unique constraint on (node_id, collected_at, pid) is the
natural dedup key: same node, same collection timestamp, same PID cannot
represent two distinct observations.

TimescaleDB note: unique constraints on hypertables must include the partition
column — collected_at is the partition column here, so the constraint is valid
on both plain Postgres and TimescaleDB.  The index backing the constraint is
created as a regular btree; TimescaleDB will automatically create per-chunk
local indexes.

Upgrade: add unique constraint (non-blocking on an empty or small table;
  on large live tables run this in a maintenance window or use
  CREATE UNIQUE INDEX CONCURRENTLY + ALTER TABLE ADD CONSTRAINT … USING INDEX).
Downgrade: drop the constraint.
"""

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_node_process_stat_node_ts_pid",
        "node_process_stats",
        ["node_id", "collected_at", "pid"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_node_process_stat_node_ts_pid", "node_process_stats", type_="unique")
