"""Add tool_mode to llm_endpoints

Revision ID: 048
Revises: 047
Create Date: 2026-06-09
"""

import sqlalchemy as sa
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_endpoints", sa.Column("tool_mode", sa.String(20), nullable=False, server_default="json"))


def downgrade() -> None:
    op.drop_column("llm_endpoints", "tool_mode")
