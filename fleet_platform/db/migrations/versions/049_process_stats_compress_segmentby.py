"""node_process_stats: add compress_segmentby=node_id

Revision ID: 049
Revises: 048
Create Date: 2026-06-09
"""

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Changing segmentby requires compression be temporarily disabled on existing chunks.
    # Decompress is implicit when altering; set both orderby+segmentby together.
    op.execute(
        "ALTER TABLE node_process_stats SET (timescaledb.compress_segmentby = 'node_id', timescaledb.compress_orderby = 'collected_at DESC')"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE node_process_stats SET (timescaledb.compress_segmentby = '', timescaledb.compress_orderby = 'collected_at DESC')"
    )
