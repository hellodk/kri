"""Null inline SSH credential columns on migrated nodes/groups (#748 — ARC-4).

Revision ID: 058
Revises: 057
Create Date: 2026-06-24

Migration 055 copied every inline ``ssh_*`` secret into the first-class
``Credential`` store and set ``credential_id`` on the owning row. The inline
columns were left in place as a one-release read-fallback (per the #704 design).

This migration completes the write-path cleanup:

- For every ``nodes`` / ``groups`` row that now has ``credential_id IS NOT NULL``
  (i.e., has been migrated), the inline ``ssh_username``, ``ssh_password_enc``,
  ``ssh_key_enc``, and ``ssh_auth_mode`` columns are NULLed / reset to default.
  Rows without a ``credential_id`` are intentionally left untouched — they never
  had inline creds to begin with, or they predated migration 055 (unlikely
  after a full run, but safe).

- The inline columns are **not dropped** here. A follow-up migration should drop
  them once the ``owner_secret_flags`` fallback read-path in
  ``services/ssh_credential_link.py`` is removed (deferred: that code is shared
  and the drop is risky without confirming all read-paths are gone).

This migration is idempotent: NULLing already-NULL columns is a no-op.

**What is deferred (#748 partial):**
- Dropping the inline columns (requires confirming the fallback read-path in
  ``services/ssh_credential_link.py:owner_secret_flags`` is removed first).
- Removing the fallback read from the resolver/service layer (owned by another
  agent — not in this file-ownership scope).
"""

import sqlalchemy as sa
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

_NULL_NODES = """
    UPDATE nodes
       SET ssh_username      = NULL,
           ssh_password_enc  = NULL,
           ssh_key_enc       = NULL,
           ssh_auth_mode     = 'password'
     WHERE credential_id IS NOT NULL
"""

_NULL_GROUPS = """
    UPDATE groups
       SET ssh_username      = NULL,
           ssh_password_enc  = NULL,
           ssh_key_enc       = NULL,
           ssh_auth_mode     = 'password'
     WHERE credential_id IS NOT NULL
"""

_RESTORE_NODES = """
    UPDATE nodes n
       SET ssh_username     = c.username,
           ssh_password_enc = CASE WHEN c.kind = 'username_password' THEN c.secret_enc ELSE NULL END,
           ssh_key_enc      = CASE WHEN c.kind = 'ssh_key'            THEN c.secret_enc ELSE NULL END,
           ssh_auth_mode    = CASE WHEN c.kind = 'ssh_key' THEN 'key' ELSE 'password' END
      FROM credentials c
     WHERE n.credential_id = c.id
       AND n.ssh_username IS NULL
"""

_RESTORE_GROUPS = """
    UPDATE groups g
       SET ssh_username     = c.username,
           ssh_password_enc = CASE WHEN c.kind = 'username_password' THEN c.secret_enc ELSE NULL END,
           ssh_key_enc      = CASE WHEN c.kind = 'ssh_key'            THEN c.secret_enc ELSE NULL END,
           ssh_auth_mode    = CASE WHEN c.kind = 'ssh_key' THEN 'key' ELSE 'password' END
      FROM credentials c
     WHERE g.credential_id = c.id
       AND g.ssh_username IS NULL
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(_NULL_NODES))
    conn.execute(sa.text(_NULL_GROUPS))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(_RESTORE_NODES))
    conn.execute(sa.text(_RESTORE_GROUPS))
