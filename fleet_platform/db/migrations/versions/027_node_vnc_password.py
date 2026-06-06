"""Add vnc_password_enc to nodes.

Stores the per-node VNC password (Fernet-encrypted at rest).  The kri VNC
proxy reads this field to perform the RFB server-side handshake so that
browser-based noVNC clients never need to know the raw VNC password.
"""

import sqlalchemy as sa
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("vnc_password_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "vnc_password_enc")
