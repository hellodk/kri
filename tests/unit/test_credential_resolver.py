# tests/unit/test_credential_resolver.py
"""Unit tests for fleet_platform.services.credential_resolver."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import (
    node_has_group,
    resolve_node_credentials,
)
from fleet_platform.services.platform_settings_svc import _fernet, encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(*scalar_returns):
    """Build an AsyncMock db whose execute() returns results in order."""
    db = AsyncMock(spec=AsyncSession)
    side_effects = []
    for val in scalar_returns:
        result = MagicMock()
        result.scalar_one_or_none.return_value = val
        side_effects.append(result)
    if len(side_effects) == 1:
        db.execute.return_value = side_effects[0]
    else:
        db.execute.side_effect = side_effects
    return db


def _node(ssh_username=None, ssh_password_enc=None, ssh_key_enc=None, ssh_auth_mode=None, ssh_host_key=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.ssh_username = ssh_username
    node.ssh_password_enc = ssh_password_enc
    node.ssh_key_enc = ssh_key_enc
    node.ssh_auth_mode = ssh_auth_mode
    node.ssh_host_key = ssh_host_key  # None = not bootstrapped; explicit to avoid MagicMock truthy default
    return node


def _group(name="mygroup", ssh_username="guser", ssh_password_enc=None, ssh_key_enc=None, ssh_auth_mode=None):
    group = MagicMock()
    group.name = name
    group.ssh_username = ssh_username
    group.ssh_password_enc = ssh_password_enc
    group.ssh_key_enc = ssh_key_enc
    group.ssh_auth_mode = ssh_auth_mode
    return group


def _platform_row(value, is_encrypted=False):
    row = MagicMock()
    row.value = value
    row.is_encrypted = is_encrypted
    return row


# ---------------------------------------------------------------------------
# Test 1: node-level creds, no secrets at all
# ---------------------------------------------------------------------------


async def test_node_level_credentials_no_secrets():
    node = _node(ssh_username="admin")
    db = AsyncMock(spec=AsyncSession)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: node-level creds, password decrypts correctly
# ---------------------------------------------------------------------------


async def test_node_level_credentials_with_encrypted_password():
    encrypted_pw = encrypt_secret("mypassword")
    node = _node(ssh_username="admin", ssh_password_enc=encrypted_pw)
    db = AsyncMock(spec=AsyncSession)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_password"] == "mypassword"
    assert result["ssh_key"] == ""


# ---------------------------------------------------------------------------
# Test 3: ssh_password_enc is garbage — exception swallowed, password=""
# ---------------------------------------------------------------------------


async def test_node_level_credentials_decrypt_failure():
    node = _node(ssh_username="admin", ssh_password_enc="not-valid-fernet-data")
    db = AsyncMock(spec=AsyncSession)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_password"] == ""


# ---------------------------------------------------------------------------
# Test 4: node-level creds with ssh_key
# ---------------------------------------------------------------------------


async def test_node_level_credentials_with_ssh_key():
    encrypted_key = encrypt_secret("SSH_KEY_PLACEHOLDER_RSA")
    node = _node(ssh_username="admin", ssh_key_enc=encrypted_key, ssh_auth_mode="key")
    db = AsyncMock(spec=AsyncSession)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_key"] == "SSH_KEY_PLACEHOLDER_RSA"
    assert result["auth_mode"] == "key"


# ---------------------------------------------------------------------------
# Test 5: group-level credentials
# ---------------------------------------------------------------------------


async def test_group_level_credentials():
    node = _node()
    group = _group(name="mygroup", ssh_username="guser")
    db = _make_db(group)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:mygroup"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == ""
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"


# ---------------------------------------------------------------------------
# Test 6: group found but ssh_password_enc=None → ssh_password=""
# ---------------------------------------------------------------------------


async def test_group_level_no_password_enc():
    node = _node()
    group = _group(ssh_username="guser", ssh_password_enc=None)
    db = _make_db(group)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"].startswith("group:")
    assert result["ssh_password"] == ""


# ---------------------------------------------------------------------------
# Test 7: global fallback, db returns None for both settings
# ---------------------------------------------------------------------------


async def test_global_fallback_no_settings():
    node = _node()
    # Three calls: group query (None), SSH_USERNAME setting (None), SSH_PASSWORD setting (None)
    db = _make_db(None, None, None)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"


# ---------------------------------------------------------------------------
# Test 8: global fallback, SSH_USERNAME setting found
# ---------------------------------------------------------------------------


async def test_global_fallback_with_setting():
    node = _node()
    user_row = _platform_row("deploy", is_encrypted=False)
    pw_row = None
    db = _make_db(None, user_row, pw_row)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "deploy"


# ---------------------------------------------------------------------------
# Test 9: global fallback, SSH_PASSWORD setting is encrypted and decrypts
# ---------------------------------------------------------------------------


async def test_global_fallback_with_encrypted_password():
    node = _node()
    encrypted_pw = _fernet().encrypt(b"secretpass").decode()
    user_row = _platform_row("admin", is_encrypted=False)
    pw_row = _platform_row(encrypted_pw, is_encrypted=True)
    db = _make_db(None, user_row, pw_row)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == "secretpass"


# ---------------------------------------------------------------------------
# Test 10: node_has_group returns True
# ---------------------------------------------------------------------------


async def test_node_has_group_true():
    member = MagicMock()
    db = _make_db(member)

    result = await node_has_group(uuid.uuid4(), db)

    assert result is True


# ---------------------------------------------------------------------------
# Test 11: node_has_group returns False
# ---------------------------------------------------------------------------


async def test_node_has_group_false():
    db = _make_db(None)

    result = await node_has_group(uuid.uuid4(), db)

    assert result is False


# ---------------------------------------------------------------------------
# Test 12: group-level — ssh_password_enc is garbage, exception swallowed
# ---------------------------------------------------------------------------


async def test_group_level_decrypt_failure_swallowed():
    node = _node()
    group = _group(ssh_username="guser", ssh_password_enc="not-valid-fernet-data")
    db = _make_db(group)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"].startswith("group:")
    assert result["ssh_password"] == ""


# ---------------------------------------------------------------------------
# Test 13: group with ssh_key decrypts correctly
# ---------------------------------------------------------------------------


async def test_group_level_with_ssh_key():
    encrypted_key = encrypt_secret("SSH_KEY_PLACEHOLDER_EC")
    node = _node()
    group = _group(ssh_username="guser", ssh_key_enc=encrypted_key, ssh_auth_mode="key")
    db = _make_db(group)

    result = await resolve_node_credentials(node, db)

    assert result["ssh_key"] == "SSH_KEY_PLACEHOLDER_EC"
    assert result["auth_mode"] == "key"


# ---------------------------------------------------------------------------
# Test 14: node ssh_auth_mode propagated when set
# ---------------------------------------------------------------------------


async def test_node_auth_mode_propagated():
    node = _node(ssh_username="admin", ssh_auth_mode="key")
    db = AsyncMock(spec=AsyncSession)

    result = await resolve_node_credentials(node, db)

    assert result["auth_mode"] == "key"


# ---------------------------------------------------------------------------
# Test 15: global fallback, SSH_PASSWORD Fernet decryption fails gracefully
# ---------------------------------------------------------------------------


async def test_node_level_ssh_key_decrypt_failure_swallowed():
    """ssh_key decryption failure is swallowed; ssh_key="" returned (covers lines 50-51)."""
    node = _node(ssh_username="admin", ssh_key_enc="not-valid-fernet-key-data")
    db = AsyncMock(spec=AsyncSession)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_key"] == ""


async def test_group_level_ssh_key_decrypt_failure_swallowed():
    """Group ssh_key decryption failure is swallowed (covers lines 90-91)."""
    encrypted_key = "not-valid-fernet-data"
    node = _node()
    group = _group(ssh_username="guser", ssh_key_enc=encrypted_key, ssh_auth_mode="key")
    db = _make_db(group)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"].startswith("group:")
    assert result["ssh_key"] == ""


async def test_global_fallback_decrypt_failure_returns_empty():
    """_get_global_setting swallows Fernet errors and returns ''."""
    node = _node()
    user_row = _platform_row("admin", is_encrypted=False)
    pw_row = _platform_row("not-valid-fernet-ciphertext", is_encrypted=True)
    db = _make_db(None, user_row, pw_row)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_password"] == ""
