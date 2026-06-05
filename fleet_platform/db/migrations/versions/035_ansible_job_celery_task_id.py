"""Add celery_task_id and cancelled_at to ansible_jobs (#342)."""

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ansible_jobs", sa.Column("celery_task_id", sa.String(255), nullable=True))
    op.add_column("ansible_jobs", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ansible_jobs", "cancelled_at")
    op.drop_column("ansible_jobs", "celery_task_id")
