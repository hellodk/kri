# tests/unit/test_credential_resolver_sync.py
"""Unit tests for the sync credential resolver used by the playbook worker (#279).

As of #989 (Chunk 1 — GROUP-ONLY credential contract) the sync resolver, like
its async twin, has exactly two tiers: ``credential_groups`` (a node's group
membership) and the controller key. There is no per-node credential, no legacy
``Group.credential_id`` column, and no global-password fallback.
"""

import uuid
from unittest.mock import MagicMock, patch

from fleet_platform.services.platform_settings_svc import encrypt_secret


class _Row:
    """Mimics a SQLAlchemy (Credential, group_name) Row consumed via ``.all()``."""

    def __init__(self, cred, name):
        self._t = (cred, name)

    def __iter__(self):
        return iter(self._t)


def _sync_db(cg_result, *scalar_returns):
    """Build a MagicMock sync Session.

    ``cg_result`` is what the credential_groups tier's ``.all()`` call
    returns (a single row, wrapped in a list — or ``[]`` for no rows). Any
    further ``scalar_returns`` are consumed in order via
    ``.scalar_one_or_none()`` by subsequent calls (e.g. SSH_USERNAME).
    """
    db = MagicMock()
    results = []

    r0 = MagicMock()
    r0.all.return_value = [cg_result] if cg_result is not None else []
    results.append(r0)

    for val in scalar_returns:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        results.append(r)

    db.execute.side_effect = results
    return db


def _node(ssh_host_key=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key
    return node


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


def test_sync_credential_group_tier():
    """Sync resolver resolves via credential_groups, source 'group:<name>'."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    cred = _credential(kind="ssh_key", username="guser", secret_plain="KEYBLOB")
    node = _node()
    db = _sync_db(_Row(cred, "prod"))

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_key"] == "KEYBLOB"
    assert result["auth_mode"] == "key"


def test_sync_none_tier():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node()
    db = _sync_db(None, _platform_row("deploy"))  # cred-group tier (no mapping), SSH_USERNAME

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "deploy"
    assert result["ssh_password"] == ""


def test_sync_credential_group_empty_secret_falls_through_to_none():
    """A group Credential with no usable secret is skipped; resolution falls
    through to the credential-less 'none' tier (no per-node fallback exists)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    empty_group_cred = _credential(kind="username_password", username="guser", secret_plain=None)
    node = _node()
    db = _sync_db(_Row(empty_group_cred, "prod"), None)  # cred-group tier, then SSH_USERNAME

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"


def test_sync_controller_key_tier():
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _sync_db(None, None)  # cred-group tier (no mapping), SSH_USERNAME for controller user

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="CONTROLLER_KEY",
    ):
        result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "controller"
    assert result["auth_mode"] == "key"
    assert result["ssh_key"] == "CONTROLLER_KEY"


def test_sync_credential_group_wins_over_controller():
    """A usable group credential wins over the controller-key tier even when
    ssh_host_key is set."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    cred = _credential(kind="username_password", username="guser", secret_plain="gpw")
    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _sync_db(_Row(cred, "prod"))

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "guser"
    assert result["ssh_password"] == "gpw"
