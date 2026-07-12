"""Repair: re-add credential_id columns an early 065 variant dropped (expand-contract).

Revision ID: 066
Revises: 065
Create Date: 2026-07-13

An early on-disk variant of migration 065 dropped ``groups.credential_id`` and
``nodes.credential_id``. The committed 065 is additive (no drop), but on any DB
where the drop-variant actually ran, alembic already records revision ``065`` as
applied and will NOT re-run it — leaving the columns missing while the code
(Node/Group models + the resolver's expand-contract fallback tiers, and every
``SELECT nodes.*`` / ``SELECT groups.*``) still references them → 500
``UndefinedColumn``.

This migration idempotently re-adds the two columns (nullable, FK to credentials)
so model and DB agree again. On a DB that still HAS the columns it is a no-op.
The final "contract" phase owns dropping them for good, once every caller is off.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "nodes", "credential_id"):
        op.add_column("nodes", sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index("idx_nodes_credential_id", "nodes", ["credential_id"])
        op.create_foreign_key(
            "fk_nodes_credential_id", "nodes", "credentials", ["credential_id"], ["id"], ondelete="SET NULL"
        )

    if not _has_column(bind, "groups", "credential_id"):
        op.add_column("groups", sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index("idx_groups_credential_id", "groups", ["credential_id"])
        op.create_foreign_key(
            "fk_groups_credential_id", "groups", "credentials", ["credential_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    # Intentional no-op: re-adding these columns is a repair. Dropping them again
    # is exactly the bug this fixes; the final contract-phase migration owns the
    # real drop once all callers are migrated off the columns.
    pass
