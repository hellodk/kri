"""Link nodes & groups to the Credential store via nullable FK (#703, #699).

Revision ID: 054
Revises: 053
Create Date: 2026-06-22

Foundation for the credential-consolidation epic (#704). Adds:
- ``nodes.credential_id``      nullable FK -> credentials.id (ON DELETE SET NULL)
- ``groups.credential_id``     nullable FK -> credentials.id (ON DELETE SET NULL)
- ``groups.credential_priority`` integer (default 0) — deterministic tiebreak
  when a node belongs to 2+ credential-bearing groups (#699), replacing the
  former ``ORDER BY name ASC`` alphabetical accident.

FKs are nullable by design: nodes are born from salt-minion check-ins with no
operator in the loop, so a mandatory credential would break auto-discovery.
The inline ``ssh_*`` columns are left intact here; the data migration (055)
populates the FKs and a later follow-up migration drops the inline columns.
"""

import sqlalchemy as sa
from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("credential_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("idx_nodes_credential_id", "nodes", ["credential_id"])
    op.create_foreign_key(
        "fk_nodes_credential_id",
        "nodes",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("groups", sa.Column("credential_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("idx_groups_credential_id", "groups", ["credential_id"])
    op.create_foreign_key(
        "fk_groups_credential_id",
        "groups",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "groups",
        sa.Column("credential_priority", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("groups", "credential_priority")
    op.drop_constraint("fk_groups_credential_id", "groups", type_="foreignkey")
    op.drop_index("idx_groups_credential_id", "groups")
    op.drop_column("groups", "credential_id")

    op.drop_constraint("fk_nodes_credential_id", "nodes", type_="foreignkey")
    op.drop_index("idx_nodes_credential_id", "nodes")
    op.drop_column("nodes", "credential_id")
