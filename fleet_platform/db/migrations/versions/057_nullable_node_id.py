"""Make pending_actions.node_id nullable (#742).

Revision ID: 057
Revises: 056
Create Date: 2026-06-23

Bug #742: ``create_proposal`` was writing ``uuid.UUID(int=0)`` (the nil UUID) as
a sentinel for "no single node target" (multi-target or unresolved minion). This
polluted FK semantics — the nil UUID is not a real ``nodes`` row.

Fix: make ``node_id`` nullable so ``NULL`` is the canonical "no node" value.

Downgrade: before re-adding the NOT NULL constraint, any existing NULLs are
back-filled with the nil UUID to avoid failures on legacy rows.
"""

import sqlalchemy as sa
from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None

_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.alter_column("pending_actions", "node_id", nullable=True)


def downgrade() -> None:
    conn = op.get_bind()
    # Back-fill NULLs with the nil UUID before restoring the NOT NULL constraint.
    conn.execute(
        sa.text("UPDATE pending_actions SET node_id = :nil WHERE node_id IS NULL"),
        {"nil": _NIL_UUID},
    )
    op.alter_column("pending_actions", "node_id", nullable=False)
