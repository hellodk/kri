"""Add bootstrap_logs column to nodes."""
import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("nodes", sa.Column("bootstrap_logs", sa.Text, nullable=True))


def downgrade():
    op.drop_column("nodes", "bootstrap_logs")
