"""Add salt_masters table and nodes.salt_master_id FK

Revision ID: 041
Revises: 040
Create Date: 2026-06-07

Part of the salt-master decoupling epic (#523, issue #516).
Designed for N masters per fleet.

Data migration (idempotent):
  If a 'salt_master_address' platform_setting exists, one salt_masters row is
  inserted (name='default', is_default=true) and all nodes are backfilled to
  point at it.  Running upgrade() twice is safe — the INSERT uses ON CONFLICT
  DO NOTHING and the UPDATE is a no-op when rows already have a value.
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create salt_masters table
    # ------------------------------------------------------------------
    op.create_table(
        "salt_masters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("publish_port", sa.Integer, nullable=False, server_default="4505"),
        sa.Column("ret_port", sa.Integer, nullable=False, server_default="4506"),
        sa.Column("control_mode", sa.String(50), nullable=False, server_default="salt_api"),
        sa.Column("api_url", sa.Text, nullable=True),
        sa.Column("api_user", sa.String(255), nullable=True),
        sa.Column("api_password_enc", sa.Text, nullable=True),
        sa.Column("api_eauth", sa.String(50), nullable=True),
        sa.Column("token_delivery", sa.String(50), nullable=False, server_default="ingest"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("checks", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_salt_masters_name"),
    )
    op.create_index("idx_salt_masters_enabled", "salt_masters", ["enabled"])
    op.create_index("idx_salt_masters_is_default", "salt_masters", ["is_default"])

    # ------------------------------------------------------------------
    # 2. Add salt_master_id FK column to nodes
    # ------------------------------------------------------------------
    op.add_column(
        "nodes",
        sa.Column(
            "salt_master_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("salt_masters.id", ondelete="SET NULL", name="fk_nodes_salt_master_id"),
            nullable=True,
        ),
    )
    op.create_index("idx_nodes_salt_master_id", "nodes", ["salt_master_id"])

    # ------------------------------------------------------------------
    # 3. Data migration — seed one default master from platform_settings
    #    Idempotent: ON CONFLICT DO NOTHING + UPDATE only unset rows.
    # ------------------------------------------------------------------
    conn = op.get_bind()

    row = conn.execute(
        sa.text("SELECT value FROM platform_settings WHERE key = 'salt_master_address' AND value IS NOT NULL LIMIT 1")
    ).fetchone()

    if row:
        address = row[0].strip()
        if address:
            master_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    """
                    INSERT INTO salt_masters (id, name, address, enabled, is_default, control_mode, token_delivery, status)
                    VALUES (:id, 'default', :address, true, true, 'salt_api', 'ingest', 'unknown')
                    ON CONFLICT (name) DO NOTHING
                    """
                ),
                {"id": master_id, "address": address},
            )
            # Fetch the actual id (may differ if DO NOTHING fired and row pre-existed)
            result = conn.execute(sa.text("SELECT id FROM salt_masters WHERE name = 'default' LIMIT 1")).fetchone()
            if result:
                actual_id = result[0]
                conn.execute(
                    sa.text("UPDATE nodes SET salt_master_id = :master_id WHERE salt_master_id IS NULL"),
                    {"master_id": actual_id},
                )


def downgrade() -> None:
    op.drop_index("idx_nodes_salt_master_id", "nodes")
    op.drop_constraint("fk_nodes_salt_master_id", "nodes", type_="foreignkey")
    op.drop_column("nodes", "salt_master_id")

    op.drop_index("idx_salt_masters_is_default", "salt_masters")
    op.drop_index("idx_salt_masters_enabled", "salt_masters")
    op.drop_table("salt_masters")
