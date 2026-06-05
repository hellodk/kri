"""Add ssh_host_key column to nodes table.

Revision ID: 023
Revises: 022
Create Date: 2026-05-27
"""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("ssh_host_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "ssh_host_key")
