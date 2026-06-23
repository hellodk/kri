"""Add SSH reachability columns to nodes (#356-ui).

Revision ID: 056
Revises: 055
Create Date: 2026-06-23

Surfaces the existing SSH probe in the UI. ``status`` is Salt minion presence;
these columns are an independent SSH-reachability axis written by the 15-minute
``check_ssh_connectivity`` sweep and the on-demand ``/ssh-test`` endpoint:

- ``ssh_state``      — ok | auth_failed | unreachable | unknown (NULL = never probed)
- ``ssh_checked_at`` — when the probe last ran
- ``ssh_detail``     — short human-readable reason (e.g. "authentication rejected")
"""

import sqlalchemy as sa
from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("ssh_state", sa.String(length=20), nullable=True))
    op.add_column("nodes", sa.Column("ssh_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("nodes", sa.Column("ssh_detail", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "ssh_detail")
    op.drop_column("nodes", "ssh_checked_at")
    op.drop_column("nodes", "ssh_state")
