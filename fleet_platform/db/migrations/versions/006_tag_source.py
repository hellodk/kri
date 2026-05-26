"""Add source column to tags table."""
import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tags",
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="user",
        ),
    )
    op.create_index("idx_tags_source", "tags", ["source"])


def downgrade():
    op.drop_index("idx_tags_source", "tags")
    op.drop_column("tags", "source")
