# tests/unit/test_credential_resolver.py
"""Unit tests for fleet_platform.services.credential_resolver.

As of #748 (ARC-4) the resolver reads secrets ONLY from the first-class
``Credential`` store (node/group ``credential_id``) plus the controller/global
platform tiers. The deprecated inline ``ssh_*`` columns are no longer consulted
— see ``test_748_no_inline_ssh_fallback.py`` for the regression guards.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import (
    node_has_group,
    resolve_node_credentials,
)
from fleet_platform.services.platform_settings_svc import _fernet, encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FirstResult:
    """Marks a value that should be returned via ``.first()`` instead of
    ``.scalar_one_or_none()`` (#984 — the credential_groups tier calls ``.first()``
    on its query result, unlike the row-returning legacy queries)."""

    def __init__(self, value):
        self.value = value


def _make_db(*scalar_returns):
    """Build an AsyncMock db whose execute() returns results in order.

    Wrap a value in :class:`_FirstResult` to have it consumed via ``.first()``
    (the #984 credential_groups tier) instead of ``.scalar_one_or_none()``.
    """
    db = AsyncMock(spec=AsyncSession)
    side_effects = []
    for val in scalar_returns:
        result = MagicMock()
        if isinstance(val, _FirstResult):
            result.first.return_value = val.value
        else:
            result.scalar_one_or_none.return_value = val
        side_effects.append(result)
    if len(side_effects) == 1:
        db.execute.return_value = side_effects[0]
    elif side_effects:
        db.execute.side_effect = side_effects
    return db


def _node(ssh_host_key=None, credential_id=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key  # None = not bootstrapped
    node.credential_id = credential_id  # None = no FK
    return node


def _group(name="mygroup", credential_id=None, credential_priority=0):
    group = MagicMock()
    group.name = name
    group.credential_id = credential_id
    group.credential_priority = credential_priority
    return group


def _credential(kind="username_password", username="cuser", secret_plain="cpw"):
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = kind
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain) if secret_plain is not None else ""
    cred.last_used_at = None
    return cred


def _platform_row(value, is_encrypted=False):
    row = MagicMock()
    row.value = value
    row.is_encrypted = is_encrypted
    return row


# ---------------------------------------------------------------------------
# Node-level Credential FK resolution
# ---------------------------------------------------------------------------


async def test_node_credential_fk_password():
    """Node FK -> username_password Credential resolves to password auth, source 'node'."""
    cred = _credential(kind="username_password", username="cuser", secret_plain="cpw")
    node = _node(credential_id=cred.id)
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "cuser"
    assert result["ssh_password"] == "cpw"
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"
    assert cred.last_used_at is not None  # touched for audit/rotation
    db.execute.assert_not_called()  # FK hit short-circuits the group query


async def test_node_credential_fk_ssh_key():
    """Node FK -> ssh_key Credential resolves to key auth."""
    cred = _credential(kind="ssh_key", username="keyuser", secret_plain="PRIVATE_KEY_BLOB")
    node = _node(credential_id=cred.id)
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "keyuser"
    assert result["ssh_key"] == "PRIVATE_KEY_BLOB"
    assert result["ssh_password"] == ""
    assert result["auth_mode"] == "key"


async def test_node_credential_secret_decrypt_failure_swallowed():
    """A node Credential whose secret_enc is garbage -> empty secret, no usable
    secret -> falls through to global. Decryption failure is logged, not raised."""
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = "username_password"
    cred.username = "cuser"
    cred.secret_enc = "not-valid-fernet-data"
    cred.last_used_at = None
    node = _node(credential_id=cred.id)
    db = _make_db(_FirstResult(None), None, None, None)  # cred-group tier, group query, 2 global settings
    db.get.return_value = cred

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_password"] == ""


async def test_node_fk_dangling_falls_through_to_global():
    """A dangling node FK (credential row gone) no longer falls back to inline
    columns (#748) — it falls all the way through to the global tier."""
    node = _node(credential_id=uuid.uuid4())
    db = _make_db(_FirstResult(None), None, None, None)  # cred-group tier, group query, 2 global settings
    db.get.return_value = None  # credential deleted out from under the FK

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"


# ---------------------------------------------------------------------------
# Group-level Credential FK resolution
# ---------------------------------------------------------------------------


async def test_group_credential_fk():
    """Group FK -> Credential resolves with source 'group:<name>'."""
    cred = _credential(kind="username_password", username="guser", secret_plain="gpw")
    group = _group(name="prod", credential_id=cred.id)
    node = _node()
    db = _make_db(_FirstResult(None), group)  # cred-group tier (no assoc row), legacy group query
    db.get = AsyncMock(return_value=cred)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == "gpw"


async def test_group_credential_fk_ssh_key():
    cred = _credential(kind="ssh_key", username="guser", secret_plain="GROUP_KEY")
    group = _group(name="prod", credential_id=cred.id)
    node = _node()
    db = _make_db(_FirstResult(None), group)  # cred-group tier (no assoc row), legacy group query
    db.get = AsyncMock(return_value=cred)

    result = await resolve_node_credentials(node, db)

    assert result["ssh_key"] == "GROUP_KEY"
    assert result["auth_mode"] == "key"


async def test_node_fk_wins_over_group():
    """When both the node FK and a group FK resolve, the node credential wins."""
    node_cred = _credential(username="nodeuser", secret_plain="nodepw")
    node = _node(credential_id=node_cred.id)
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = node_cred

    result = await resolve_node_credentials(node, db)

    assert result["ssh_user"] == "nodeuser"
    db.execute.assert_not_called()


async def test_node_fk_empty_secret_falls_through_to_group():
    """A node FK pointing at a secret-less credential (#704 Class-A defect) is
    skipped; resolution falls through to the usable group credential."""
    empty_node_cred = _credential(kind="username_password", username="nuser", secret_plain=None)
    group_cred = _credential(kind="username_password", username="guser", secret_plain="gpw")
    group = _group(name="prod", credential_id=group_cred.id)
    node = _node(credential_id=empty_node_cred.id)
    db = _make_db(_FirstResult(None), group)  # cred-group tier (no assoc row), legacy group query

    async def _get(_model, ident):
        return empty_node_cred if ident == empty_node_cred.id else group_cred

    db.get = AsyncMock(side_effect=_get)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == "gpw"


async def test_node_fk_empty_secret_falls_through_to_global():
    """An empty node FK with no group falls all the way through to global."""
    empty_node_cred = _credential(kind="username_password", username="nuser", secret_plain=None)
    node = _node(credential_id=empty_node_cred.id)
    db = _make_db(_FirstResult(None), None, None, None)  # cred-group tier, group query, SSH_USERNAME, SSH_PASSWORD
    db.get = AsyncMock(return_value=empty_node_cred)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"


# ---------------------------------------------------------------------------
# Controller-key tier
# ---------------------------------------------------------------------------


async def test_controller_key_tier():
    """Bootstrapped node (ssh_host_key set), no credential -> controller key."""
    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _make_db(
        _FirstResult(None), None, None
    )  # cred-group tier, legacy group query (None), SSH_USERNAME for controller user

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="CONTROLLER_KEY",
    ):
        result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "controller"
    assert result["auth_mode"] == "key"
    assert result["ssh_key"] == "CONTROLLER_KEY"


# ---------------------------------------------------------------------------
# Global fallback tier
# ---------------------------------------------------------------------------


async def test_global_fallback_no_settings():
    node = _node()
    db = _make_db(_FirstResult(None), None, None, None)  # cred-group, group, SSH_USERNAME, SSH_PASSWORD all None

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"


async def test_global_fallback_with_setting():
    node = _node()
    db = _make_db(_FirstResult(None), None, _platform_row("deploy", is_encrypted=False), None)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "deploy"


async def test_global_fallback_with_encrypted_password():
    node = _node()
    encrypted_pw = _fernet().encrypt(b"secretpass").decode()
    user_row = _platform_row("admin", is_encrypted=False)
    pw_row = _platform_row(encrypted_pw, is_encrypted=True)
    db = _make_db(_FirstResult(None), None, user_row, pw_row)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == "secretpass"


async def test_global_fallback_decrypt_failure_returns_empty():
    """_get_global_setting swallows Fernet errors and returns ''."""
    node = _node()
    user_row = _platform_row("admin", is_encrypted=False)
    pw_row = _platform_row("not-valid-fernet-ciphertext", is_encrypted=True)
    db = _make_db(_FirstResult(None), None, user_row, pw_row)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_password"] == ""


# ---------------------------------------------------------------------------
# node_has_group
# ---------------------------------------------------------------------------


async def test_node_has_group_true():
    member = MagicMock()
    db = _make_db(member)

    result = await node_has_group(uuid.uuid4(), db)

    assert result is True


async def test_node_has_group_false():
    db = _make_db(None)

    result = await node_has_group(uuid.uuid4(), db)

    assert result is False
