"""Add salt_api_port and use_tls to salt_masters for SSoT api_url derivation.

Revision ID: 044
Revises: 043
Create Date: 2026-06-07

Issue #562 (single source of truth for salt masters):
  - salt_api_port: Integer, NOT NULL, default 8080
  - use_tls: Boolean, NOT NULL, default True
  These two columns, together with `address`, fully determine api_url.
"""

import sqlalchemy as sa
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "salt_masters",
        sa.Column(
            "salt_api_port",
            sa.Integer,
            nullable=False,
            server_default="8080",
        ),
    )
    op.add_column(
        "salt_masters",
        sa.Column(
            "use_tls",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("salt_masters", "use_tls")
    op.drop_column("salt_masters", "salt_api_port")
