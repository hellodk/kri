"""Add functional indexes on cast(id::text) for UUID prefix search on job tables."""
from alembic import op

revision = '036'
down_revision = '035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # text_pattern_ops enables LIKE prefix matching on the cast expression
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ansible_jobs_id_text "
        "ON ansible_jobs (cast(id AS text) text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_execution_jobs_id_text "
        "ON execution_jobs (cast(id AS text) text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_query_log_id_text "
        "ON llm_query_log (cast(id AS text) text_pattern_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_llm_query_log_id_text")
    op.execute("DROP INDEX IF EXISTS idx_execution_jobs_id_text")
    op.execute("DROP INDEX IF EXISTS idx_ansible_jobs_id_text")
