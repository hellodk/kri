"""Migrate inline node/group SSH creds into Credential rows (#697).

Revision ID: 055
Revises: 054
Create Date: 2026-06-22

Part of the credential-consolidation epic (#704). For every node/group that
carries inline SSH credentials (``ssh_username`` set), create a named
``Credential`` row and point its ``credential_id`` FK at it.

Design (settled in the 2026-06-22 epic review):
- **Copy ciphertext verbatim.** ``node/group.ssh_*_enc`` and
  ``credentials.secret_enc`` share the same Fernet key, so we move the existing
  ciphertext without a decrypt/re-encrypt round-trip — no plaintext in memory.
- **No value-dedup in v1.** One Credential per source row; identical secrets are
  not coalesced (that would require decrypting every secret to hash it).
- **auth_mode -> kind:** ``ssh_auth_mode='key'`` -> ``kind='ssh_key'`` (secret =
  key blob); otherwise ``kind='username_password'`` (secret = password). When a
  row carries both a password and a key, the active ``auth_mode`` wins; the other
  secret is left behind in the (still-present) inline column.
- **Idempotent:** only rows with ``credential_id IS NULL`` are touched, so a
  re-run is a no-op. The inline columns are intentionally left intact (staged
  drop in a follow-up migration) as a one-release read-fallback.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None

# Marker stored in ``credentials.description`` so downgrade can identify and
# remove exactly the rows this migration created.
_MARKER = "migrated-from-inline-ssh#697"


def _unique_name(conn, base: str) -> str:
    """Return ``base`` or, if a credential already owns that name, ``base-<8hex>``."""
    exists = conn.execute(sa.text("SELECT 1 FROM credentials WHERE name = :n LIMIT 1"), {"n": base}).first()
    if not exists:
        return base
    return f"{base}-{uuid.uuid4().hex[:8]}"


# Fully-literal SQL per owner table (no identifier interpolation — keeps the
# static analyzer happy and the queries trivially auditable).
_NODE_SELECT = (
    "SELECT id, minion_id AS owner_name, ssh_username, ssh_password_enc, "
    "ssh_key_enc, ssh_auth_mode FROM nodes "
    "WHERE ssh_username IS NOT NULL AND credential_id IS NULL"
)
_NODE_UPDATE = "UPDATE nodes SET credential_id = :cid WHERE id = :rid"
_GROUP_SELECT = (
    "SELECT id, name AS owner_name, ssh_username, ssh_password_enc, "
    "ssh_key_enc, ssh_auth_mode FROM groups "
    "WHERE ssh_username IS NOT NULL AND credential_id IS NULL"
)
_GROUP_UPDATE = "UPDATE groups SET credential_id = :cid WHERE id = :rid"

_INSERT_CRED = (
    "INSERT INTO credentials (id, name, kind, username, secret_enc, description, created_at) "
    "VALUES (:id, :name, :kind, :username, :secret_enc, :description, now())"
)


def _migrate_table(conn, *, select_sql: str, update_sql: str, name_prefix: str) -> None:
    rows = conn.execute(sa.text(select_sql)).fetchall()

    for r in rows:
        is_key = (r.ssh_auth_mode or "password") == "key"
        kind = "ssh_key" if is_key else "username_password"
        # Copy the matching ciphertext verbatim; '' (encrypts to NOT NULL-safe
        # empty) when the row had a username but no secret of that kind.
        secret_enc = (r.ssh_key_enc if is_key else r.ssh_password_enc) or ""
        name = _unique_name(conn, f"{name_prefix}{r.owner_name}")
        cred_id = uuid.uuid4()

        conn.execute(
            sa.text(_INSERT_CRED),
            {
                "id": cred_id,
                "name": name,
                "kind": kind,
                "username": r.ssh_username,
                "secret_enc": secret_enc,
                "description": _MARKER,
            },
        )
        conn.execute(sa.text(update_sql), {"cid": cred_id, "rid": r.id})


def upgrade() -> None:
    conn = op.get_bind()
    _migrate_table(conn, select_sql=_NODE_SELECT, update_sql=_NODE_UPDATE, name_prefix="node:")
    _migrate_table(conn, select_sql=_GROUP_SELECT, update_sql=_GROUP_UPDATE, name_prefix="group:")


def downgrade() -> None:
    conn = op.get_bind()
    # Null out FKs that point at migration-created credentials, then delete them.
    conn.execute(
        sa.text(
            "UPDATE nodes SET credential_id = NULL WHERE credential_id IN "
            "(SELECT id FROM credentials WHERE description = :m)"
        ),
        {"m": _MARKER},
    )
    conn.execute(
        sa.text(
            "UPDATE groups SET credential_id = NULL WHERE credential_id IN "
            "(SELECT id FROM credentials WHERE description = :m)"
        ),
        {"m": _MARKER},
    )
    conn.execute(sa.text("DELETE FROM credentials WHERE description = :m"), {"m": _MARKER})
