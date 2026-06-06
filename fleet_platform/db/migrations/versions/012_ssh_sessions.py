"""ssh_sessions

Revision ID: 012
Revises: 011
Create Date: 2026-05-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ssh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("credential_source", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("alert_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_ip", sa.String(45), nullable=True),
        sa.Column("ssh_user", sa.String(255), nullable=True),
    )
    op.create_index("idx_ssh_sessions_node", "ssh_sessions", ["node_id"])
    op.create_index("idx_ssh_sessions_user", "ssh_sessions", ["user_id"])
    op.create_index("idx_ssh_sessions_started", "ssh_sessions", ["started_at"])

    op.create_table(
        "session_recordings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ssh_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_recordings_session", "session_recordings", ["session_id"])

    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ssh_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_security_events_session", "security_events", ["session_id"])
    op.create_index("idx_security_events_created", "security_events", ["created_at"])


def downgrade():
    op.drop_table("security_events")
    op.drop_table("session_recordings")
    op.drop_table("ssh_sessions")
