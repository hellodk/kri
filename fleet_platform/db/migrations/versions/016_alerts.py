"""alerts

Revision ID: 016
Revises: 015
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'alert_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('TRUE')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'webhook_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('type', sa.String(32), nullable=False, server_default='slack'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('TRUE')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'alert_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('alert_rules.id', ondelete='CASCADE'), nullable=True),
        sa.Column('node_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('fired_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('delivered', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
    )
    op.create_index('idx_alert_events_fired_at', 'alert_events', ['fired_at'])
    op.create_index('idx_alert_events_rule_node', 'alert_events', ['rule_id', 'node_id'])


def downgrade():
    op.drop_table('alert_events')
    op.drop_table('webhook_configs')
    op.drop_table('alert_rules')
