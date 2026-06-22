"""Agent apply-with-approval: co-sign tracking on pending_actions (#714)

Revision ID: 053
Revises: 052
Create Date: 2026-06-22

Phase E of the agentic transformation epic (#716). Adds the co-sign audit trail
to ``pending_actions`` so a > N-node agent-proposed action requires both an
operator and an admin sign-off, and every approval is attributed to a human:
- ``approved_by``     first approver (operator or admin) email
- ``approved_at``     timestamp of first approval
- ``co_signed_by``    second (admin) co-signer email, when co-sign is required
- ``co_signed_at``    timestamp of co-sign
"""

import sqlalchemy as sa
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pending_actions", sa.Column("approved_by", sa.String(length=255), nullable=True))
    op.add_column("pending_actions", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pending_actions", sa.Column("co_signed_by", sa.String(length=255), nullable=True))
    op.add_column("pending_actions", sa.Column("co_signed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("pending_actions", "co_signed_at")
    op.drop_column("pending_actions", "co_signed_by")
    op.drop_column("pending_actions", "approved_at")
    op.drop_column("pending_actions", "approved_by")
