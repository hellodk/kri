"""Create llm_endpoints and llm_query_log tables

Revision ID: 018
Revises: 017
Create Date: 2026-05-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text, nullable=True),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default=sa.text("4096")),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_llm_endpoints_is_default", "llm_endpoints", ["is_default"])
    op.create_index("idx_llm_endpoints_enabled", "llm_endpoints", ["enabled"])

    op.create_table(
        "llm_query_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_endpoints.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("intent", sa.String(30), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("response", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(255), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_llm_query_log_user_id", "llm_query_log", ["user_id", "created_at"])
    op.create_index("idx_llm_query_log_endpoint_id", "llm_query_log", ["endpoint_id"])


def downgrade() -> None:
    op.drop_table("llm_query_log")
    op.drop_table("llm_endpoints")
