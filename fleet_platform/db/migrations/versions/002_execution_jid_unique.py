"""Add unique constraint on execution_jobs(salt_jid, target_id) for idempotency

Revision ID: 002
Revises: 001
Create Date: 2026-05-13
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Allow NULL salt_jid (internal jobs without a Salt JID); only enforce uniqueness when both are non-NULL
    op.create_index(
        "uq_exec_jobs_jid_target",
        "execution_jobs",
        ["salt_jid", "target_id"],
        unique=True,
        postgresql_where="salt_jid IS NOT NULL AND target_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_exec_jobs_jid_target", table_name="execution_jobs")
