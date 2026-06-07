"""Add provision lifecycle columns + master_provision_runs table

Revision ID: 043
Revises: 042
Create Date: 2026-06-07

Issue #556 (master-lifecycle epic):
  - provision_status, os_family, salt_version, last_provisioned_at, provision_error
  - ssh_host, ssh_user, ssh_key_enc, ssh_password_enc  (per-master SSH creds, Fernet)
  - node_id FK (optional link to a node record, SET NULL on deletion)
  - master_provision_runs table (audit trail for install/configure runs)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add provision lifecycle columns to salt_masters
    # ------------------------------------------------------------------
    op.add_column(
        "salt_masters",
        sa.Column(
            "provision_status",
            sa.String(20),
            nullable=False,
            server_default="unprovisioned",
        ),
    )
    op.add_column(
        "salt_masters",
        sa.Column("os_family", sa.String(20), nullable=True),
    )
    op.add_column(
        "salt_masters",
        sa.Column("salt_version", sa.String(50), nullable=True),
    )
    op.add_column(
        "salt_masters",
        sa.Column("last_provisioned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "salt_masters",
        sa.Column("provision_error", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. SSH credentials columns (Fernet-encrypted)
    # ------------------------------------------------------------------
    op.add_column(
        "salt_masters",
        sa.Column("ssh_host", sa.String(255), nullable=True),
    )
    op.add_column(
        "salt_masters",
        sa.Column("ssh_user", sa.String(255), nullable=True),
    )
    op.add_column(
        "salt_masters",
        sa.Column("ssh_key_enc", sa.Text, nullable=True),
    )
    op.add_column(
        "salt_masters",
        sa.Column("ssh_password_enc", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. Optional node_id FK (SET NULL on deletion)
    # ------------------------------------------------------------------
    op.add_column(
        "salt_masters",
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="SET NULL", name="fk_salt_masters_node_id"),
            nullable=True,
        ),
    )
    op.create_index("idx_salt_masters_node_id", "salt_masters", ["node_id"])

    # ------------------------------------------------------------------
    # 4. Create master_provision_runs table
    # ------------------------------------------------------------------
    op.create_table(
        "master_provision_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "salt_master_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("salt_masters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(20), nullable=False, server_default="install"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ansible_stdout", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("triggered_by", sa.String(255), nullable=True),
    )
    op.create_index(
        "idx_master_provision_runs_salt_master_id",
        "master_provision_runs",
        ["salt_master_id"],
    )


def downgrade() -> None:
    # Reverse order
    op.drop_index("idx_master_provision_runs_salt_master_id", "master_provision_runs")
    op.drop_table("master_provision_runs")

    op.drop_index("idx_salt_masters_node_id", "salt_masters")
    op.drop_constraint("fk_salt_masters_node_id", "salt_masters", type_="foreignkey")
    op.drop_column("salt_masters", "node_id")

    op.drop_column("salt_masters", "ssh_password_enc")
    op.drop_column("salt_masters", "ssh_key_enc")
    op.drop_column("salt_masters", "ssh_user")
    op.drop_column("salt_masters", "ssh_host")

    op.drop_column("salt_masters", "provision_error")
    op.drop_column("salt_masters", "last_provisioned_at")
    op.drop_column("salt_masters", "salt_version")
    op.drop_column("salt_masters", "os_family")
    op.drop_column("salt_masters", "provision_status")
