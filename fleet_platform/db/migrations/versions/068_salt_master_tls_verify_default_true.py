"""Change salt_masters.tls_verify server_default to true (S3, #1005)

Revision ID: 068
Revises: 067
Create Date: 2026-07-13

Issue #1005 (S3): tls_verify defaulted to False (migration 042), so salt-api
calls skipped TLS verification unless an operator explicitly opted in —
MITM-able on a hostile LAN. This migration flips the column's server_default
to true so NEW masters verify TLS by default; operators must now opt OUT
rather than opt in.

This migration only changes the column default used for future INSERTs where
the application does not supply an explicit value. It intentionally does
NOT backfill existing rows — an existing master that was provisioned with
tls_verify=false (e.g. because it uses a self-signed cert the operator
already accepted) keeps that value untouched. Flipping existing rows could
break salt-api connectivity for masters that rely on the current behavior;
that migration would need to be a deliberate, separate, operator-reviewed
change.

Idempotent/reversible: upgrade re-applies the same server_default if run
twice; downgrade restores the original false default from migration 042.
"""

import sqlalchemy as sa
from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "salt_masters",
        "tls_verify",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "salt_masters",
        "tls_verify",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
        existing_nullable=False,
    )
