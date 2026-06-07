"""Enforce at most one default salt master via a partial-unique index.

Revision ID: 046
Revises: 045
Create Date: 2026-06-08

Issue #579 (architecture hardening):
  Without a DB constraint, multiple rows could carry is_default=true (or the
  default could be deleted entirely), breaking salt_keys._get_default_master().
  This adds a PostgreSQL partial-unique index so only ONE row may have
  is_default = true. Existing duplicates are demoted (keeping the most recently
  updated) before the index is created so the migration is idempotent on dirty data.
"""

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive: collapse any pre-existing duplicate defaults down to one
    # (keep the most recently updated row as the canonical default).
    op.execute(
        """
        UPDATE salt_masters
        SET is_default = false
        WHERE is_default = true
          AND id NOT IN (
            SELECT id FROM salt_masters
            WHERE is_default = true
            ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
            LIMIT 1
          )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_salt_masters_one_default ON salt_masters (is_default) WHERE is_default"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_salt_masters_one_default")
