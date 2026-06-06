"""Add timeout_seconds column to ansible_jobs (#348)."""

import sqlalchemy as sa
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ansible_jobs", sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="1800"))


def downgrade() -> None:
    op.drop_column("ansible_jobs", "timeout_seconds")
