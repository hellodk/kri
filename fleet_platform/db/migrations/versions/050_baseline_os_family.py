"""Add os_family to desired_state_baselines for OS-aware lookup.

Revision ID: 050
Revises: 049
Create Date: 2026-06-13

A baseline can now declare an os_family ('Darwin', 'Linux', 'FreeBSD',
'Windows'). When find_baseline_for_node selects a baseline for a node, it
prefers rows whose os_family matches the node's derived family and falls
back to OS-agnostic rows (os_family IS NULL). This lets a single fleet
share a global baseline while letting macOS-only nodes pin to a Darwin
baseline (#prod-os-baselines).
"""

import sqlalchemy as sa
from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "desired_state_baselines",
        sa.Column("os_family", sa.String(20), nullable=True),
    )
    # Speeds the OS-aware lookup that filters first by target_type and then
    # by os_family. Partial index keeps it cheap (most rows will be
    # OS-agnostic).
    op.create_index(
        "idx_baselines_os_family",
        "desired_state_baselines",
        ["target_type", "os_family"],
        postgresql_where=sa.text("os_family IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_baselines_os_family", "desired_state_baselines")
    op.drop_column("desired_state_baselines", "os_family")
