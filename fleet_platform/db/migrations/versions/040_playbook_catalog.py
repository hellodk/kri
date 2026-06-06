"""Add playbook_catalog and playbook_favorites tables

Revision ID: 040
Revises: 039
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbook_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_key", sa.Text, nullable=False),
        sa.Column("source_label", sa.String(255), nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("enabled_by", sa.String(255), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_key", "filename", name="uq_catalog_source_filename"),
    )
    op.create_index("idx_catalog_enabled", "playbook_catalog", ["enabled"])
    op.create_index("idx_catalog_source_key", "playbook_catalog", ["source_key"])

    op.create_table(
        "playbook_favorites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "catalog_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playbook_catalog.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "catalog_id", name="uq_favorite_user_catalog"),
    )
    op.create_index("idx_favorite_user_id", "playbook_favorites", ["user_id"])


def downgrade() -> None:
    op.drop_table("playbook_favorites")
    op.drop_index("idx_catalog_source_key", "playbook_catalog")
    op.drop_index("idx_catalog_enabled", "playbook_catalog")
    op.drop_table("playbook_catalog")
