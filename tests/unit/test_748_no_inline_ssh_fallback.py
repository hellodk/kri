"""#748 (ARC-4): the inline SSH credential read-fallback is gone.

Before #748, ``credential_resolver`` and ``ssh_credential_link`` read the
deprecated inline ``ssh_*`` columns on nodes/groups as a fallback when no
``credential_id`` was set — a second secret-resolution path. These tests pin the
new contract:

* resolution flows ONLY through the ``Credential`` store (+ controller/global
  platform tiers), never the inline columns;
* a node whose only "credential" would have been inline data resolves to no
  usable secret and :func:`require_usable_node_credentials` raises;
* the inline helper functions are gone, so the dual path cannot silently come
  back. (The inline columns themselves remain on the model for now — the
  physical DROP migration is deferred until the remaining inline readers in
  sibling-owned ``workers``/``api`` modules are removed.)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services import credential_resolver
from fleet_platform.services.credential_resolver import (
    NoUsableCredentialError,
    require_usable_node_credentials,
    require_usable_node_credentials_sync,
    resolve_node_credentials,
    resolve_node_credentials_sync,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(*scalar_returns):
    """AsyncMock db whose execute() returns scalar_one_or_none results in order."""
    db = AsyncMock(spec=AsyncSession)
    side_effects = []
    for val in scalar_returns:
        result = MagicMock()
        result.scalar_one_or_none.return_value = val
        side_effects.append(result)
    if len(side_effects) == 1:
        db.execute.return_value = side_effects[0]
    elif side_effects:
        db.execute.side_effect = side_effects
    return db


def _sync_db(*scalar_returns):
    db = MagicMock()
    side_effects = []
    for val in scalar_returns:
        result = MagicMock()
        result.scalar_one_or_none.return_value = val
        side_effects.append(result)
    if len(side_effects) == 1:
        db.execute.return_value = side_effects[0]
    elif side_effects:
        db.execute.side_effect = side_effects
    return db


def _node_with_inline(credential_id=None, ssh_host_key=None):
    """A node carrying *only* legacy inline-style attributes (no credential_id).

    Uses a plain MagicMock so the inline attributes exist as object attributes —
    if the resolver still read them, these poison values would leak into the
    result. They must not.
    """
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "legacy-node-01"
    node.credential_id = credential_id
    node.ssh_host_key = ssh_host_key
    node.ssh_username = "inline-operator"
    node.ssh_password_enc = encrypt_secret("inline-secret")
    node.ssh_key_enc = encrypt_secret("inline-key")
    node.ssh_auth_mode = "password"
    return node


def _credential(kind="username_password", username="cuser", secret_plain="cpw"):
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = kind
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain) if secret_plain is not None else ""
    cred.last_used_at = None
    return cred


# ---------------------------------------------------------------------------
# Credential-store resolution still works (happy path preserved)
# ---------------------------------------------------------------------------


async def test_resolve_with_credential_id_works():
    cred = _credential(username="cuser", secret_plain="cpw")
    node = MagicMock()
    node.id = uuid.uuid4()
    node.credential_id = cred.id
    node.ssh_host_key = None
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "cuser"
    assert result["ssh_password"] == "cpw"
    db.execute.assert_not_called()


def test_resolve_sync_with_credential_id_works():
    cred = _credential(kind="ssh_key", username="keyuser", secret_plain="KEYBLOB")
    node = MagicMock()
    node.id = uuid.uuid4()
    node.credential_id = cred.id
    node.ssh_host_key = None
    db = MagicMock()
    db.get.return_value = cred

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_key"] == "KEYBLOB"
    assert result["auth_mode"] == "key"


# ---------------------------------------------------------------------------
# Inline columns are never read
# ---------------------------------------------------------------------------


async def test_node_inline_data_ignored_no_credential_id():
    """A node with inline ssh_* attrs but no credential_id must NOT resolve to
    the inline values — it falls through to the global tier instead."""
    node = _node_with_inline()
    # group query -> None, SSH_USERNAME -> None, SSH_PASSWORD -> None
    db = _make_db(None, None, None)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"  # global default, not "inline-operator"
    assert result["ssh_password"] == ""  # the inline secret is never read
    assert result["ssh_key"] == ""


def test_sync_node_inline_data_ignored_no_credential_id():
    node = _node_with_inline()
    db = _sync_db(None, None, None)

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""


async def test_group_inline_only_not_selected_as_primary():
    """A member group with only inline ssh_username (no credential_id) is no
    longer eligible — the group tier is skipped and resolution hits global."""
    group = MagicMock()
    group.name = "legacy-group"
    group.credential_id = None
    group.ssh_username = "group-inline-user"
    node = _node_with_inline()
    # Even if a group row were returned, a None credential_id means skip it.
    db = _make_db(group, None, None)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"


def test_primary_group_stmt_filters_on_credential_id_only():
    """The group selection must be eligible by credential_id only — the inline
    ``ssh_username`` column must NOT appear in the WHERE filter (the SELECT list
    still mentions every column while the deprecated columns remain on the model,
    so we assert on the predicate, not the projection)."""
    stmt = credential_resolver._primary_group_stmt(uuid.uuid4())
    where_sql = str(stmt.whereclause)
    assert "credential_id IS NOT NULL" in where_sql
    assert "ssh_username" not in where_sql


# ---------------------------------------------------------------------------
# Loud failure: missing credential raises instead of degrading silently
# ---------------------------------------------------------------------------


async def test_require_raises_for_inline_only_node():
    """A node with only inline data and no credential_id has no usable secret —
    require_usable_node_credentials must raise the documented error."""
    node = _node_with_inline()
    db = _make_db(None, None, None)

    try:
        await require_usable_node_credentials(node, db)
        raise AssertionError("expected NoUsableCredentialError")
    except NoUsableCredentialError as exc:
        assert "legacy-node-01" in str(exc)


def test_require_sync_raises_for_inline_only_node():
    node = _node_with_inline()
    db = _sync_db(None, None, None)

    try:
        require_usable_node_credentials_sync(node, db)
        raise AssertionError("expected NoUsableCredentialError")
    except NoUsableCredentialError as exc:
        assert "credential_id" in str(exc)


async def test_require_returns_creds_when_credential_present():
    cred = _credential(username="cuser", secret_plain="cpw")
    node = MagicMock()
    node.id = uuid.uuid4()
    node.credential_id = cred.id
    node.ssh_host_key = None
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    result = await require_usable_node_credentials(node, db)

    assert result["ssh_password"] == "cpw"


# ---------------------------------------------------------------------------
# Structural guards: the dual path cannot silently return
# ---------------------------------------------------------------------------


def test_inline_helpers_removed():
    assert not hasattr(credential_resolver, "_inline_node_creds")
    assert not hasattr(credential_resolver, "_inline_group_creds")


async def test_owner_secret_flags_ignores_inline_columns():
    """owner_secret_flags no longer reads the inline columns: even when inline
    ciphertext is supplied, an owner with no credential_id reports no secret."""
    from fleet_platform.services.ssh_credential_link import owner_secret_flags

    db = AsyncMock(spec=AsyncSession)
    has_password, has_key = await owner_secret_flags(
        db,
        credential_id=None,
        inline_password_enc=encrypt_secret("legacy-inline-pw"),
        inline_key_enc=encrypt_secret("legacy-inline-key"),
    )

    assert has_password is False
    assert has_key is False
    db.get.assert_not_called()


async def test_owner_secret_flags_reads_credential_store():
    from fleet_platform.services.ssh_credential_link import owner_secret_flags

    cred = _credential(kind="username_password", secret_plain="cpw")
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    has_password, has_key = await owner_secret_flags(db, credential_id=cred.id)

    assert has_password is True
    assert has_key is False
