"""group_credentials

Revision ID: 011
Revises: 010
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('groups', sa.Column('ssh_username', sa.String(255), nullable=True))
    op.add_column('groups', sa.Column('ssh_password_enc', sa.Text(), nullable=True))
    op.add_column('groups', sa.Column('ssh_auth_mode', sa.String(10), nullable=True, server_default='password'))
    op.add_column('groups', sa.Column('ssh_key_enc', sa.Text(), nullable=True))
    op.add_column('groups', sa.Column('session_max_mins', sa.Integer(), nullable=True, server_default='60'))
    op.add_column('groups', sa.Column('session_retention_days', sa.Integer(), nullable=True, server_default='30'))
    op.add_column('groups', sa.Column('require_group', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    for col in ['ssh_username', 'ssh_password_enc', 'ssh_auth_mode', 'ssh_key_enc',
                'session_max_mins', 'session_retention_days', 'require_group']:
        op.drop_column('groups', col)
