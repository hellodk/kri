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


def _node(
    ssh_username=None,
    ssh_password_enc=None,
    ssh_key_enc=None,
    ssh_auth_mode=None,
    ssh_host_key=None,
    credential_id=None,
):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.ssh_username = ssh_username
    node.ssh_password_enc = ssh_password_enc
    node.ssh_key_enc = ssh_key_enc
    node.ssh_auth_mode = ssh_auth_mode
    node.ssh_host_key = ssh_host_key  # None = not bootstrapped; explicit to avoid MagicMock truthy default
    node.credential_id = credential_id  # None = no FK; explicit to avoid MagicMock truthy default
    return node


def _group(
    name="mygroup",
    ssh_username="guser",
    ssh_password_enc=None,
    ssh_key_enc=None,
    ssh_auth_mode=None,
    credential_id=None,
    credential_priority=0,
):
    group = MagicMock()
    group.name = name
    group.ssh_username = ssh_username
    group.ssh_password_enc = ssh_password_enc
    group.ssh_key_enc = ssh_key_enc
    group.ssh_auth_mode = ssh_auth_mode
    group.credential_id = credential_id  # None = no FK; explicit to avoid MagicMock truthy default
    group.credential_priority = credential_priority
    return group


def _credential(kind="username_password", username="cuser", secret_plain="cpw"):
    from fleet_platform.services.platform_settings_svc import encrypt_secret

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


# ---------------------------------------------------------------------------
# Credential-store FK resolution (#698)
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


async def test_node_fk_wins_over_inline():
    """When both the node FK and inline creds are set, the FK credential wins."""
    cred = _credential(kind="username_password", username="fkuser", secret_plain="fkpw")
    node = _node(ssh_username="inlineuser", credential_id=cred.id)
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    result = await resolve_node_credentials(node, db)

    assert result["ssh_user"] == "fkuser"


async def test_node_fk_dangling_falls_back_to_inline():
    """A dangling node FK (credential row gone) falls back to inline node creds."""
    node = _node(ssh_username="inlineuser", ssh_password_enc=encrypt_secret("inlinepw"), credential_id=uuid.uuid4())
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = None  # credential deleted out from under the FK

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "inlineuser"
    assert result["ssh_password"] == "inlinepw"


async def test_group_credential_fk():
    """Group FK -> Credential resolves with source 'group:<name>'."""
    cred = _credential(kind="username_password", username="guser", secret_plain="gpw")
    group = _group(name="prod", ssh_username=None, credential_id=cred.id)
    node = _node()
    db = _make_db(group)
    db.get = AsyncMock(return_value=cred)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == "gpw"


async def test_node_fk_empty_secret_falls_through_to_group():
    """A node FK pointing at a secret-less credential (#704 Class-A defect) is
    skipped; resolution falls through to the usable group credential instead of
    short-circuiting to the dead node FK."""
    empty_node_cred = _credential(kind="username_password", username="nuser", secret_plain=None)
    group_cred = _credential(kind="username_password", username="guser", secret_plain="gpw")
    group = _group(name="prod", ssh_username=None, credential_id=group_cred.id)
    node = _node(credential_id=empty_node_cred.id)
    db = _make_db(group)

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
    # group query (None), SSH_USERNAME (None), SSH_PASSWORD (None)
    db = _make_db(None, None, None)
    db.get = AsyncMock(return_value=empty_node_cred)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
