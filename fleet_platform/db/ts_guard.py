"""TimescaleDB availability guards for Alembic migrations (#665).

On vanilla PostgreSQL (CI, dev laptops, air-gapped/standalone deploys) the
``timescaledb`` extension is not installed. Migrations that call
``create_hypertable`` / ``add_compression_policy`` / ``add_retention_policy``
or create ``timescaledb.continuous`` aggregates fail there and block every
later migration. These helpers let migrations degrade to plain tables instead:
the schema is identical, only the hypertable partitioning/compression/retention
features are skipped when the extension is absent.
"""

from __future__ import annotations

from alembic import op


def timescale_available() -> bool:
    """True if the timescaledb extension *files* are present and CREATE-able.

    Checks ``pg_available_extensions`` (what the server could install), used to
    decide whether ``CREATE EXTENSION timescaledb`` is safe to run.
    """
    bind = op.get_bind()
    row = bind.exec_driver_sql("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'").first()
    return row is not None


def timescale_enabled() -> bool:
    """True if the timescaledb extension is actually installed in this database.

    Checks ``pg_extension``; gate hypertable/compression/retention/continuous
    -aggregate calls on this so they run only where TimescaleDB is live.
    """
    bind = op.get_bind()
    row = bind.exec_driver_sql("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'").first()
    return row is not None
