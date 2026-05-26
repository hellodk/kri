"""ios_tracking

Revision ID: 017
Revises: 016
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('nodes', sa.Column('xcode_version', sa.String(32), nullable=True))
    op.add_column('nodes', sa.Column('macos_version', sa.String(32), nullable=True))

    op.create_table(
        'certificates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('node_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('cert_type', sa.String(64), nullable=False),
        sa.Column('team_id', sa.String(64), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=False),
        sa.Column('fingerprint', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_certificates_node', 'certificates', ['node_id'])
    op.create_index('idx_certificates_expiry', 'certificates', ['expiry_date'])

    op.create_table(
        'jenkins_agents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('node_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('jenkins_url', sa.String(512), nullable=False),
        sa.Column('agent_name', sa.String(256), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('node_id', name='uq_jenkins_agents_node'),
    )
    op.create_index('idx_jenkins_agents_node', 'jenkins_agents', ['node_id'])


def downgrade():
    op.drop_table('jenkins_agents')
    op.drop_table('certificates')
    op.drop_column('nodes', 'macos_version')
    op.drop_column('nodes', 'xcode_version')
