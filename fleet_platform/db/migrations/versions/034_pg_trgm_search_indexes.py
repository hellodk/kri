"""Enable pg_trgm extension and add trigram indexes for fuzzy unified search."""
from alembic import op

revision = '034'
down_revision = '033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Trigram indexes for fuzzy search on the most-searched text columns
    op.execute("CREATE INDEX IF NOT EXISTS idx_nodes_hostname_trgm ON nodes USING gin (hostname gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_nodes_minion_id_trgm ON nodes USING gin (minion_id gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_groups_name_trgm ON groups USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ansible_jobs_playbook_trgm ON ansible_jobs USING gin (playbook gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ansible_jobs_target_label_trgm ON ansible_jobs USING gin (target_label gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_llm_query_log_prompt_trgm ON llm_query_log USING gin (prompt gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_llm_query_log_prompt_trgm")
    op.execute("DROP INDEX IF EXISTS idx_ansible_jobs_target_label_trgm")
    op.execute("DROP INDEX IF EXISTS idx_ansible_jobs_playbook_trgm")
    op.execute("DROP INDEX IF EXISTS idx_groups_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_nodes_minion_id_trgm")
    op.execute("DROP INDEX IF EXISTS idx_nodes_hostname_trgm")
