"""Drop deprecated inline SSH credential columns from nodes and groups (#913).

Revision ID: 063
Revises: 062
Create Date: 2026-06-26

Migration 055 copied every inline ``ssh_*`` secret into the first-class
``Credential`` store.  Migration 058 NULLed the columns on all rows that
had been migrated.  The service layer removed its read-fallback path in #748
(ARC-4).  The remaining inline readers in ``workers/ansible_tasks`` and
``api/routes`` were migrated to the credential resolver in #913/#919.

This migration completes the cleanup by physically dropping the four columns
from both ``nodes`` and ``groups``:

  - ``ssh_username``
  - ``ssh_password_enc``
  - ``ssh_key_enc``
  - ``ssh_auth_mode``

Columns that are **NOT** dropped (out of scope):
  - ``nodes.ssh_host_key``   — host identity for known_hosts, not a credential
  - ``nodes.ssh_port``       — connection parameter (if present)
  - ``nodes.credential_id``  — FK to the Credential store (the replacement)
  - ``groups.credential_id`` — same
  - ``salt_masters.*``       — different table, different epic

Downgrade re-adds all four columns as nullable (safe: data was NULLed in 058).
"""

import sqlalchemy as sa
from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None

_TABLES = ("nodes", "groups")
_COLUMNS = [
    ("ssh_username", sa.String(255)),
    ("ssh_password_enc", sa.Text()),
    ("ssh_key_enc", sa.Text()),
    ("ssh_auth_mode", sa.String(10)),
]


def upgrade() -> None:
    for table in _TABLES:
        for col_name, _ in _COLUMNS:
            op.drop_column(table, col_name)


def downgrade() -> None:
    for table in _TABLES:
        for col_name, col_type in _COLUMNS:
            op.add_column(table, sa.Column(col_name, col_type, nullable=True))
