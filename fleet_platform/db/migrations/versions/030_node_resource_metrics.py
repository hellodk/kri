"""Add resource metric columns to nodes table (#287)."""

import sqlalchemy as sa
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("cpu_usage_pct", sa.Float(), nullable=True))
    op.add_column("nodes", sa.Column("mem_usage_pct", sa.Float(), nullable=True))
    op.add_column("nodes", sa.Column("disk_io_read_kbs", sa.Float(), nullable=True))
    op.add_column("nodes", sa.Column("disk_io_write_kbs", sa.Float(), nullable=True))
    op.add_column("nodes", sa.Column("gpu_usage_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    for col in ("gpu_usage_pct", "disk_io_write_kbs", "disk_io_read_kbs", "mem_usage_pct", "cpu_usage_pct"):
        op.drop_column("nodes", col)
