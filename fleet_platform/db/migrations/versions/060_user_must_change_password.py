"""Add must_change_password column to users (#757/#820).

Revision ID: 058
Revises: 057
Create Date: 2026-06-24

Adds a boolean flag that the seeding logic sets to True when an account is
bootstrapped with a weak/default password.  The login route gate-checks this
flag and returns 403 MUST_CHANGE_PASSWORD, forcing the operator to set a
proper password via the admin UI before the account can be used.

Upgrade: ADD COLUMN with server default false (non-blocking on large tables;
  no backfill needed — all existing accounts started with their own passwords).
Downgrade: DROP COLUMN.
"""

import sqlalchemy as sa
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
