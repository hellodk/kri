# tests/unit/test_credential_resolver_sync.py
"""Unit tests for the sync credential resolver used by the playbook worker (#279)."""

import uuid
from unittest.mock import MagicMock

from fleet_platform.services.platform_settings_svc import _fernet, encrypt_secret


def _sync_db(*scalar_returns):
    """Build a MagicMock sync Session whose execute() returns results in order."""
    db = MagicMock()
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


def _node(ssh_username=None, ssh_password_enc=None, ssh_key_enc=None, ssh_auth_mode=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.ssh_username = ssh_username
    node.ssh_password_enc = ssh_password_enc
    node.ssh_key_enc = ssh_key_enc
    node.ssh_auth_mode = ssh_auth_mode
    return node


def _group(name="prod", ssh_username="guser", ssh_password_enc=None, ssh_key_enc=None, ssh_auth_mode=None):
    g = MagicMock()
    g.name = name
    g.ssh_username = ssh_username
    g.ssh_password_enc = ssh_password_enc
    g.ssh_key_enc = ssh_key_enc
    g.ssh_auth_mode = ssh_auth_mode
    return g


def _platform_row(value, is_encrypted=False):
    row = MagicMock()
    row.value = value
    row.is_encrypted = is_encrypted
    return row


def test_sync_node_level_credentials():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node(ssh_username="admin", ssh_password_enc=encrypt_secret("pw"))
    db = MagicMock()
    result = resolve_node_credentials_sync(node, db)
    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == "pw"
    db.execute.assert_not_called()


def test_sync_group_level_credentials():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node()
    group = _group(name="prod", ssh_username="guser", ssh_password_enc=encrypt_secret("gpw"))
    db = _sync_db(group)
    result = resolve_node_credentials_sync(node, db)
    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == "gpw"


def test_sync_global_fallback():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node()
    encrypted_pw = _fernet().encrypt(b"secretpass").decode()
    db = _sync_db(None, _platform_row("deploy"), _platform_row(encrypted_pw, is_encrypted=True))
    result = resolve_node_credentials_sync(node, db)
    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "deploy"
    assert result["ssh_password"] == "secretpass"


def test_sync_node_key_auth_mode():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node(ssh_username="admin", ssh_key_enc=encrypt_secret("KEYDATA"), ssh_auth_mode="key")
    result = resolve_node_credentials_sync(node, MagicMock())
    assert result["auth_mode"] == "key"
    assert result["ssh_key"] == "KEYDATA"
