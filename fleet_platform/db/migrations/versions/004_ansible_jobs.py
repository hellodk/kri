"""Add ansible_jobs table."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ansible_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("playbook", sa.String(255), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("target_label", sa.String(255), nullable=False),
        sa.Column("extravars", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("triggered_by", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stdout", sa.Text, nullable=True),
        sa.Column("rc", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_ansible_jobs_status", "ansible_jobs", ["status", "created_at"])


def downgrade():
    op.drop_index("idx_ansible_jobs_status", "ansible_jobs")
    op.drop_table("ansible_jobs")
