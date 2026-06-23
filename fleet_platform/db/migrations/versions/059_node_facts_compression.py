"""Add TimescaleDB compression policy to node_facts (#753 — ARC-9).

Revision ID: 059
Revises: 058
Create Date: 2026-06-24

``node_facts`` was created as a hypertable with a 90-day retention policy in
migration 001, but no compression policy was added — unlike ``node_health_snapshots``
and ``ansible_jobs`` (migration 024) and ``node_process_stats`` (migration 047).

At ~300 nodes every 5 minutes each pushing 5-20 KB of JSONB grain data, the
uncompressed table grows ~500 MB/day (~45 GB over the 90-day retention window).
TimescaleDB typically achieves 5-10× compression on columnar JSONB data, bringing
that to ~5-9 GB.

Fix: enable compression with ``node_id`` as the segment-by column (matching the
``idx_node_facts_node_id`` index), then add a policy that compresses chunks
older than 7 days — giving a one-week window of uncompressed fast-access data.

No-op on vanilla PostgreSQL (CI, dev laptops) where TimescaleDB is not installed;
guarded by ``timescale_enabled()`` identical to migrations 024/047/049.
"""

from alembic import op

from fleet_platform.db.ts_guard import timescale_enabled

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not timescale_enabled():
        return

    op.execute(
        "ALTER TABLE node_facts SET ("
        "timescaledb.compress = true, "
        "timescaledb.compress_segmentby = 'node_id', "
        "timescaledb.compress_orderby = 'collected_at DESC'"
        ")"
    )
    op.execute("SELECT add_compression_policy('node_facts', INTERVAL '7 days')")


def downgrade() -> None:
    if not timescale_enabled():
        return

    op.execute("SELECT remove_compression_policy('node_facts', if_exists => true)")
    op.execute("ALTER TABLE node_facts SET (timescaledb.compress = false)")
