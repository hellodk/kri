"""Add tls_verify and auto_accept columns to salt_masters

Revision ID: 042
Revises: 041
Create Date: 2026-06-07

Issue #555: per-master TLS verify flag (default False — accept self-signed/HTTP)
and auto-accept flag (default True — kri accepts the bootstrapped minion key via
salt-api automatically after a successful bootstrap run).
"""

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column(
        "salt_masters",
        sa.Column(
            "tls_verify",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "salt_masters",
        sa.Column(
            "auto_accept",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("salt_masters", "auto_accept")
    op.drop_column("salt_masters", "tls_verify")
