"""Convert node_health_snapshots and ansible_jobs to TimescaleDB hypertables

Revision ID: 024
Revises: 023
Create Date: 2026-05-28
"""

from alembic import op

from fleet_platform.db.ts_guard import timescale_enabled

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── node_health_snapshots ─────────────────────────────────────────
    # The composite-PK change is valid on plain Postgres too, so it runs
    # unconditionally; only the hypertable/compression/retention features are
    # gated on TimescaleDB being installed (#665).
    op.execute("ALTER TABLE node_health_snapshots DROP CONSTRAINT node_health_snapshots_pkey")
    op.execute("ALTER TABLE node_health_snapshots ADD PRIMARY KEY (id, collected_at)")
    op.execute("ALTER TABLE ansible_jobs DROP CONSTRAINT ansible_jobs_pkey")
    op.execute("ALTER TABLE ansible_jobs ADD PRIMARY KEY (id, created_at)")

    if not timescale_enabled():
        return

    op.execute(
        "SELECT create_hypertable('node_health_snapshots', by_range('collected_at', INTERVAL '1 day'), migrate_data => true)"
    )
    # Enable compression before adding compression policy (required in TimescaleDB 2.x+)
    op.execute(
        "ALTER TABLE node_health_snapshots SET (timescaledb.compress = true, timescaledb.compress_orderby = 'collected_at DESC')"
    )
    op.execute("SELECT add_compression_policy('node_health_snapshots', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('node_health_snapshots', INTERVAL '90 days')")

    # ── ansible_jobs ─────────────────────────────────────────────────
    op.execute(
        "SELECT create_hypertable('ansible_jobs', by_range('created_at', INTERVAL '1 day'), migrate_data => true)"
    )
    # Enable compression before adding compression policy
    op.execute(
        "ALTER TABLE ansible_jobs SET (timescaledb.compress = true, timescaledb.compress_orderby = 'created_at DESC')"
    )
    op.execute("SELECT add_compression_policy('ansible_jobs', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('ansible_jobs', INTERVAL '90 days')")


def downgrade() -> None:
    # Hypertable conversion is not reversible without data migration.
    # Remove policies only where TimescaleDB created them; tables remain.
    if not timescale_enabled():
        return
    op.execute("SELECT remove_retention_policy('ansible_jobs', true)")
    op.execute("SELECT remove_compression_policy('ansible_jobs', true)")
    op.execute("SELECT remove_retention_policy('node_health_snapshots', true)")
    op.execute("SELECT remove_compression_policy('node_health_snapshots', true)")
