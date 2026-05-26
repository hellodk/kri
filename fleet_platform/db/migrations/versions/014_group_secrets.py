"""group_secrets

Revision ID: 014
Revises: 013
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'group_secrets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(128), nullable=False),
        sa.Column('encrypted_value', sa.Text(), nullable=False),
        sa.Column('description', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_group_secrets_group', 'group_secrets', ['group_id'])
    op.create_index('uq_group_secrets_group_key', 'group_secrets', ['group_id', 'key'], unique=True)


def downgrade():
    op.drop_table('group_secrets')
