"""Add model_context_length and model_capabilities to llm_endpoints (#273)."""

import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_endpoints", sa.Column("model_context_length", sa.Integer(), nullable=True))
    op.add_column("llm_endpoints", sa.Column("model_capabilities", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_endpoints", "model_capabilities")
    op.drop_column("llm_endpoints", "model_context_length")
