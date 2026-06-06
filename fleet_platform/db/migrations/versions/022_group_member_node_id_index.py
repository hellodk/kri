"""add index on group_members.node_id

Revision ID: 022
Revises: 021
Create Date: 2026-05-27

"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index may already exist from the initial schema migration (001).
    # Use IF NOT EXISTS to make this idempotent.
    op.execute("CREATE INDEX IF NOT EXISTS idx_group_members_node_id ON group_members (node_id)")


def downgrade() -> None:
    op.drop_index("idx_group_members_node_id", table_name="group_members")
