"""Add pending_actions table for email approval gate (#291)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '031'
down_revision = '030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pending_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('node_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('params', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('requested_by', sa.String(255), nullable=False),
        sa.Column('approval_token', sa.String(64), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_pending_actions_token', 'pending_actions', ['approval_token'], unique=True)
    op.create_index('idx_pending_actions_status', 'pending_actions', ['status'])


def downgrade() -> None:
    op.drop_index('idx_pending_actions_status', table_name='pending_actions')
    op.drop_index('idx_pending_actions_token', table_name='pending_actions')
    op.drop_table('pending_actions')
