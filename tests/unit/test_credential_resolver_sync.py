# tests/unit/test_credential_resolver_sync.py
"""Unit tests for the sync credential resolver used by the playbook worker (#279).

As of #748 (ARC-4) the sync resolver, like its async twin, reads secrets only
from the ``Credential`` store plus the controller/global platform tiers — never
the deprecated inline ``ssh_*`` columns.
"""

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
    elif side_effects:
        db.execute.side_effect = side_effects
    return db


def _node(ssh_host_key=None, credential_id=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key
    node.credential_id = credential_id
    return node


def _group(name="prod", credential_id=None, credential_priority=0):
    g = MagicMock()
    g.name = name
    g.credential_id = credential_id
    g.credential_priority = credential_priority
    return g


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


def test_sync_node_credential_fk():
    """Sync resolver dereferences node.credential_id, source 'node' (#698)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    cred = _credential(kind="username_password", username="cuser", secret_plain="cpw")
    node = _node(credential_id=cred.id)
    db = MagicMock()
    db.get.return_value = cred

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "cuser"
    assert result["ssh_password"] == "cpw"
    db.execute.assert_not_called()


def test_sync_group_credential_fk():
    """Sync resolver dereferences group.credential_id, source 'group:<name>' (#698)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    cred = _credential(kind="ssh_key", username="guser", secret_plain="KEYBLOB")
    group = _group(name="prod", credential_id=cred.id)
    node = _node()
    db = _sync_db(group)
    db.get.return_value = cred

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_key"] == "KEYBLOB"
    assert result["auth_mode"] == "key"


def test_sync_global_fallback():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node()
    encrypted_pw = _fernet().encrypt(b"secretpass").decode()
    db = _sync_db(None, _platform_row("deploy"), _platform_row(encrypted_pw, is_encrypted=True))
    result = resolve_node_credentials_sync(node, db)
    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "deploy"
    assert result["ssh_password"] == "secretpass"


def test_sync_node_fk_empty_secret_falls_through_to_group():
    """Sync twin: an empty-secret node FK (#704 Class-A defect) is skipped and
    resolution falls through to the usable group credential."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    empty_node_cred = _credential(kind="username_password", username="nuser", secret_plain=None)
    group_cred = _credential(kind="username_password", username="guser", secret_plain="gpw")
    group = _group(name="prod", credential_id=group_cred.id)
    node = _node(credential_id=empty_node_cred.id)
    db = _sync_db(group)
    db.get.side_effect = lambda _model, ident: empty_node_cred if ident == empty_node_cred.id else group_cred

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == "gpw"
