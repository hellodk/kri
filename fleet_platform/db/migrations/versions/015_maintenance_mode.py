"""Add maintenance_mode to nodes table."""

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column(
        'nodes',
        sa.Column('maintenance_mode', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade():
    op.drop_column('nodes', 'maintenance_mode')
