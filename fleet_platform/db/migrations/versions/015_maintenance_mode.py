"""Add maintenance_mode to nodes table."""

import sqlalchemy as sa
from alembic import op

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'nodes',
        sa.Column('maintenance_mode', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade():
    op.drop_column('nodes', 'maintenance_mode')
