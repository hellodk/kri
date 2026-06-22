"""Agent foundations: agent_sessions table + agentic columns (#710)

Revision ID: 052
Revises: 051
Create Date: 2026-06-22

Phase A of the agentic transformation epic (#716):
- new ``agent_sessions`` table (one bounded agent run, owned by an operator)
- ``llm_query_log``: tool_calls (JSONB), parent_query_id (self-FK), agent_session_id
- ``pending_actions``: session_id, proposed_by_agent, tool_name, target_count,
  dry_run_result, co_sign_required
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("initial_prompt", sa.Text(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["endpoint_id"], ["llm_endpoints.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_agent_sessions_user_id", "agent_sessions", ["user_id", "created_at"])
    op.create_index("idx_agent_sessions_status", "agent_sessions", ["status"])

    # llm_query_log agentic columns
    op.add_column("llm_query_log", sa.Column("tool_calls", postgresql.JSONB(), nullable=True))
    op.add_column("llm_query_log", sa.Column("parent_query_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("llm_query_log", sa.Column("agent_session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_llm_query_log_parent",
        "llm_query_log",
        "llm_query_log",
        ["parent_query_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_llm_query_log_agent_session",
        "llm_query_log",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_llm_query_log_agent_session_id", "llm_query_log", ["agent_session_id"])

    # pending_actions agent write-path columns
    op.add_column("pending_actions", sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "pending_actions",
        sa.Column("proposed_by_agent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("pending_actions", sa.Column("tool_name", sa.String(length=100), nullable=True))
    op.add_column("pending_actions", sa.Column("target_count", sa.Integer(), nullable=True))
    op.add_column("pending_actions", sa.Column("dry_run_result", sa.Text(), nullable=True))
    op.add_column(
        "pending_actions",
        sa.Column("co_sign_required", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_foreign_key(
        "fk_pending_actions_session",
        "pending_actions",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_pending_actions_session_id", "pending_actions", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_pending_actions_session_id", table_name="pending_actions")
    op.drop_constraint("fk_pending_actions_session", "pending_actions", type_="foreignkey")
    op.drop_column("pending_actions", "co_sign_required")
    op.drop_column("pending_actions", "dry_run_result")
    op.drop_column("pending_actions", "target_count")
    op.drop_column("pending_actions", "tool_name")
    op.drop_column("pending_actions", "proposed_by_agent")
    op.drop_column("pending_actions", "session_id")

    op.drop_index("idx_llm_query_log_agent_session_id", table_name="llm_query_log")
    op.drop_constraint("fk_llm_query_log_agent_session", "llm_query_log", type_="foreignkey")
    op.drop_constraint("fk_llm_query_log_parent", "llm_query_log", type_="foreignkey")
    op.drop_column("llm_query_log", "agent_session_id")
    op.drop_column("llm_query_log", "parent_query_id")
    op.drop_column("llm_query_log", "tool_calls")

    op.drop_index("idx_agent_sessions_status", table_name="agent_sessions")
    op.drop_index("idx_agent_sessions_user_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
