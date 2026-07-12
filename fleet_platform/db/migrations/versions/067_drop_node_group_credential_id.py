"""Contract phase: drop nodes.credential_id and groups.credential_id (#989 Chunk 1).

Revision ID: 067
Revises: 066
Create Date: 2026-07-13

The credential model is now GROUP-ONLY: a node's SSH credential is resolved
exclusively via its group membership (``credential_groups`` association, #983-
#985) or the controller key — never a per-node FK, never a legacy
``Group.credential_id`` FK. Both the resolver (#989 Chunk 1) and every route/
service caller have been migrated off these two columns, so this migration
performs the final "contract" drop that migration 066's docstring promised.

No production data exists at the time of this migration — there is nothing to
backfill or preserve. Each drop is idempotent (existence-checked) so it is
also safe to run against a DB where the columns were already removed by some
other path, or one where 066's repair never ran.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_fk(bind, table: str, fk_name: str) -> bool:
    insp = sa.inspect(bind)
    return any(fk["name"] == fk_name for fk in insp.get_foreign_keys(table))


def _has_index(bind, table: str, index_name: str) -> bool:
    insp = sa.inspect(bind)
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()

    if _has_column(bind, "nodes", "credential_id"):
        if _has_fk(bind, "nodes", "fk_nodes_credential_id"):
            op.drop_constraint("fk_nodes_credential_id", "nodes", type_="foreignkey")
        if _has_index(bind, "nodes", "idx_nodes_credential_id"):
            op.drop_index("idx_nodes_credential_id", table_name="nodes")
        op.drop_column("nodes", "credential_id")

    if _has_column(bind, "groups", "credential_id"):
        if _has_fk(bind, "groups", "fk_groups_credential_id"):
            op.drop_constraint("fk_groups_credential_id", "groups", type_="foreignkey")
        if _has_index(bind, "groups", "idx_groups_credential_id"):
            op.drop_index("idx_groups_credential_id", table_name="groups")
        op.drop_column("groups", "credential_id")


def downgrade() -> None:
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
