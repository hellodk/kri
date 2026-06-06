"""Add bootstrap fields to nodes and platform_settings table."""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("nodes", sa.Column("bootstrap_status", sa.String(20), nullable=False, server_default="unregistered"))
    op.add_column("nodes", sa.Column("bootstrap_ip", sa.String(45), nullable=True))
    op.add_column("nodes", sa.Column("bootstrap_error", sa.Text, nullable=True))

    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("is_encrypted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("platform_settings")
    op.drop_column("nodes", "bootstrap_error")
    op.drop_column("nodes", "bootstrap_ip")
    op.drop_column("nodes", "bootstrap_status")
