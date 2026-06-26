# tests/unit/test_inline_ssh_columns_dropped_913.py
"""Regression guard: inline SSH credential columns removed from nodes/groups (#913).

Asserts:
  1. The four deprecated columns are no longer defined on the Node / Group models.
  2. node_credentials._get_node_credentials / _get_group_credentials are gone.
  3. A node/group create + credential link results in a fully resolvable credential
     via the Credential store (no inline-column path needed).

Run: pytest tests/unit/test_inline_ssh_columns_dropped_913.py -q
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Column definitions removed from ORM models
# ---------------------------------------------------------------------------

DROPPED_COLUMNS = ("ssh_username", "ssh_password_enc", "ssh_key_enc", "ssh_auth_mode")
KEPT_COLUMNS = ("ssh_host_key", "credential_id")


def test_node_model_no_inline_ssh_columns():
    """Node model must not define the four dropped inline SSH columns."""
    from fleet_platform.models.node import Node

    mapper = Node.__mapper__
    col_names = {c.key for c in mapper.columns}
    for col in DROPPED_COLUMNS:
        assert col not in col_names, f"Node.{col} should have been dropped in migration 063 (#913)"


def test_group_model_no_inline_ssh_columns():
    """Group model must not define the four dropped inline SSH columns."""
    from fleet_platform.models.group import Group

    mapper = Group.__mapper__
    col_names = {c.key for c in mapper.columns}
    for col in DROPPED_COLUMNS:
        assert col not in col_names, f"Group.{col} should have been dropped in migration 063 (#913)"


def test_node_model_keeps_host_key_and_credential_id():
    """Node model must retain ssh_host_key and credential_id (not credentials)."""
    from fleet_platform.models.node import Node

    mapper = Node.__mapper__
    col_names = {c.key for c in mapper.columns}
    for col in KEPT_COLUMNS:
        assert col in col_names, f"Node.{col} must be kept"


def test_group_model_keeps_credential_id():
    """Group model must retain credential_id."""
    from fleet_platform.models.group import Group

    mapper = Group.__mapper__
    col_names = {c.key for c in mapper.columns}
    assert "credential_id" in col_names, "Group.credential_id must be kept"


# ---------------------------------------------------------------------------
# 2. Deleted helper functions are gone
# ---------------------------------------------------------------------------


def test_node_credentials_helpers_deleted():
    """_get_node_credentials and _get_group_credentials must no longer exist."""
    import fleet_platform.services.node_credentials as nc

    assert not hasattr(nc, "_get_node_credentials"), (
        "_get_node_credentials was deleted in #913; it reads dropped columns"
    )
    assert not hasattr(nc, "_get_group_credentials"), (
        "_get_group_credentials was deleted in #913; it reads dropped columns"
    )


def test_ansible_tasks_no_inline_helper_import():
    """ansible_tasks must not import _get_node_credentials."""
    import fleet_platform.workers.ansible_tasks as at

    assert not hasattr(at, "_get_node_credentials"), "ansible_tasks must not expose _get_node_credentials after #913"


# ---------------------------------------------------------------------------
# 3. Credential resolution still works via the Credential store
# ---------------------------------------------------------------------------


def _make_credential(kind="username_password", username="deploy", secret_enc="enc-secret"):
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = kind
    cred.username = username
    cred.secret_enc = secret_enc
    cred.last_used_at = None
    return cred


def test_resolve_node_credentials_sync_via_store():
    """resolve_node_credentials_sync resolves creds from the Credential store without any inline column."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
    from fleet_platform.services.platform_settings_svc import encrypt_secret

    cred = _make_credential(kind="username_password", username="deploy", secret_enc=encrypt_secret("s3cr3t"))

    node = MagicMock()
    node.id = uuid.uuid4()
    node.credential_id = cred.id
    node.ssh_host_key = None

    db = MagicMock()
    db.get.return_value = cred
    db.execute.return_value.scalar_one_or_none.return_value = None

    result = resolve_node_credentials_sync(node, db)

    assert result["ssh_user"] == "deploy"
    assert result["ssh_password"] == "s3cr3t"
    assert result["credential_source"] == "node"
    assert result["auth_mode"] == "password"


def test_resolve_node_credentials_sync_falls_through_to_global():
    """With no credential_id and no host key, resolver falls through to global settings."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = MagicMock()
    node.id = uuid.uuid4()
    node.credential_id = None
    node.ssh_host_key = None

    db = MagicMock()
    db.get.return_value = None

    setting_row = MagicMock()
    setting_row.value = "globaluser"
    setting_row.is_encrypted = False

    execute_result = MagicMock()
    execute_result.scalar_one_or_none.side_effect = [
        None,  # group query
        setting_row,  # SSH_USERNAME global setting
        None,  # SSH_PASSWORD global setting
    ]
    db.execute.return_value = execute_result

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "globaluser"


def test_ssh_credential_link_owner_secret_flags_no_inline_params():
    """owner_secret_flags must no longer accept inline_password_enc/inline_key_enc."""
    import inspect

    from fleet_platform.services.ssh_credential_link import owner_secret_flags

    sig = inspect.signature(owner_secret_flags)
    assert "inline_password_enc" not in sig.parameters, (
        "inline_password_enc was removed from owner_secret_flags in #913"
    )
    assert "inline_key_enc" not in sig.parameters, "inline_key_enc was removed from owner_secret_flags in #913"
