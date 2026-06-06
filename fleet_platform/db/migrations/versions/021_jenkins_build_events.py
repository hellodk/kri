"""add jenkins_build_events table

Revision ID: 021
Revises: 020
Create Date: 2026-05-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jenkins_build_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_name", sa.String(255), nullable=False),
        sa.Column("build_number", sa.Integer, nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("test_pass", sa.Integer, nullable=True),
        sa.Column("test_fail", sa.Integer, nullable=True),
        sa.Column("test_total", sa.Integer, nullable=True),
        sa.Column("node_name", sa.String(255), nullable=True),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.UniqueConstraint("job_name", "build_number", name="uq_jenkins_build_job_number"),
    )
    op.create_index("idx_jenkins_build_started_at", "jenkins_build_events", ["started_at"])
    op.create_index("idx_jenkins_build_result", "jenkins_build_events", ["result"])


def downgrade() -> None:
    op.drop_index("idx_jenkins_build_result")
    op.drop_index("idx_jenkins_build_started_at")
    op.drop_table("jenkins_build_events")
