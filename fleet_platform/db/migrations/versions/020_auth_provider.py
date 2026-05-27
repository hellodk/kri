"""Add auth_provider to users table."""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(20), nullable=False, server_default="local"),
    )


def downgrade():
    op.drop_column("users", "auth_provider")
