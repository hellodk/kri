"""Widen llm_endpoints.provider column from 20 to 50 chars to support new provider names."""

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE llm_endpoints ALTER COLUMN provider TYPE varchar(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_endpoints ALTER COLUMN provider TYPE varchar(20)")
