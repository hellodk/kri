"""Add mobileconfig_profiles, profile_group_assignments, profile_deployment_logs tables (#264)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mobileconfig_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('payload_xml', sa.Text(), nullable=False),
        sa.Column('profile_uuid', sa.String(128), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_mobileconfig_profiles_uuid', 'mobileconfig_profiles', ['profile_uuid'])

    op.create_table(
        'profile_group_assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('profile_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('mobileconfig_profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('group_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_profile_group_profile', 'profile_group_assignments', ['profile_id'])
    op.create_index('idx_profile_group_group', 'profile_group_assignments', ['group_id'])

    op.create_table(
        'profile_deployment_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('profile_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('mobileconfig_profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('deployed_by', sa.String(256), nullable=True),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_profile_deploy_profile', 'profile_deployment_logs', ['profile_id'])
    op.create_index('idx_profile_deploy_node', 'profile_deployment_logs', ['node_id'])


def downgrade() -> None:
    op.drop_index('idx_profile_deploy_node', table_name='profile_deployment_logs')
    op.drop_index('idx_profile_deploy_profile', table_name='profile_deployment_logs')
    op.drop_table('profile_deployment_logs')

    op.drop_index('idx_profile_group_group', table_name='profile_group_assignments')
    op.drop_index('idx_profile_group_profile', table_name='profile_group_assignments')
    op.drop_table('profile_group_assignments')

    op.drop_index('idx_mobileconfig_profiles_uuid', table_name='mobileconfig_profiles')
    op.drop_table('mobileconfig_profiles')
