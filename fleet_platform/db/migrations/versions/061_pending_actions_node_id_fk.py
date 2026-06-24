"""Add FK constraint pending_actions.node_id → nodes.id (#672).

Revision ID: 061
Revises: 060
Create Date: 2026-06-24

pending_actions.node_id was nullable but had no foreign-key constraint, so
stale references to deleted nodes were never cleaned up and the column had no
referential integrity.

Upgrade: add FK with ON DELETE SET NULL (matching the nullable column —
  when a node is deleted its pending actions remain for audit purposes but
  the node reference is cleared automatically by Postgres).
Downgrade: drop the FK constraint.
"""

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_pending_actions_node_id",
        "pending_actions",
        "nodes",
        ["node_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_pending_actions_node_id", "pending_actions", type_="foreignkey")
