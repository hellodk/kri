"""Add per-node SSH credentials."""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("nodes", sa.Column("ssh_username", sa.String(255), nullable=True))
    op.add_column("nodes", sa.Column("ssh_password_enc", sa.Text, nullable=True))
    op.add_column("nodes", sa.Column("ssh_auth_mode", sa.String(10), nullable=False, server_default="password"))
    op.add_column("nodes", sa.Column("ssh_key_enc", sa.Text, nullable=True))


def downgrade():
    op.drop_column("nodes", "ssh_username")
    op.drop_column("nodes", "ssh_password_enc")
    op.drop_column("nodes", "ssh_auth_mode")
    op.drop_column("nodes", "ssh_key_enc")
