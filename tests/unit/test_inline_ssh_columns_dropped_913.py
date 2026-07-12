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
KEPT_COLUMNS = ("ssh_host_key",)
# Dropped for good in #989 Chunk 1 (contract phase, migration 067) — the
# credential model is GROUP-ONLY now: no per-node or per-group FK.
GROUP_ONLY_DROPPED_COLUMNS = ("credential_id",)


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


def test_node_model_keeps_host_key():
    """Node model must retain ssh_host_key (controller-key tier depends on it)."""
    from fleet_platform.models.node import Node

    mapper = Node.__mapper__
    col_names = {c.key for c in mapper.columns}
    for col in KEPT_COLUMNS:
        assert col in col_names, f"Node.{col} must be kept"


def test_node_model_no_credential_id():
    """Node.credential_id must be gone (#989 — group-only credential model)."""
    from fleet_platform.models.node import Node

    mapper = Node.__mapper__
    col_names = {c.key for c in mapper.columns}
    for col in GROUP_ONLY_DROPPED_COLUMNS:
        assert col not in col_names, f"Node.{col} should have been dropped in migration 067 (#989)"


def test_group_model_no_credential_id():
    """Group.credential_id must be gone (#989 — group-only credential model)."""
    from fleet_platform.models.group import Group

    mapper = Group.__mapper__
    col_names = {c.key for c in mapper.columns}
    for col in GROUP_ONLY_DROPPED_COLUMNS:
        assert col not in col_names, f"Group.{col} should have been dropped in migration 067 (#989)"


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
    """resolve_node_credentials_sync resolves creds from the Credential store via
    a node's group (credential_groups) — the ONLY per-node secret source (#989)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
    from fleet_platform.services.platform_settings_svc import encrypt_secret

    cred = _make_credential(kind="username_password", username="deploy", secret_enc=encrypt_secret("s3cr3t"))

    node = MagicMock()
    node.id = uuid.uuid4()
    node.ssh_host_key = None

    db = MagicMock()
    cg_result = MagicMock()
    cg_result.all.return_value = [(cred, "prod")]  # credential_groups tier resolves
    db.execute.return_value = cg_result

    result = resolve_node_credentials_sync(node, db)

    assert result["ssh_user"] == "deploy"
    assert result["ssh_password"] == "s3cr3t"
    assert result["credential_source"] == "group:prod"
    assert result["auth_mode"] == "password"


def test_resolve_node_credentials_sync_falls_through_to_none():
    """With no credential_groups mapping and no host key, resolver falls through
    to the credential-less 'none' tier — there is no global password fallback (#989)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = MagicMock()
    node.id = uuid.uuid4()
    node.ssh_host_key = None

    setting_row = MagicMock()
    setting_row.value = "globaluser"
    setting_row.is_encrypted = False

    execute_result = MagicMock()
    execute_result.all.return_value = []  # credential_groups tier (#984) → no mapping
    execute_result.scalar_one_or_none.side_effect = [
        setting_row,  # SSH_USERNAME global setting (login user only, never a password)
    ]
    db = MagicMock()
    db.execute.return_value = execute_result

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "globaluser"
    assert result["ssh_password"] == ""


def test_ssh_credential_link_owner_secret_flags_no_inline_params():
    """owner_secret_flags must no longer accept inline_password_enc/inline_key_enc."""
    import inspect

    from fleet_platform.services.ssh_credential_link import owner_secret_flags

    sig = inspect.signature(owner_secret_flags)
    assert "inline_password_enc" not in sig.parameters, (
        "inline_password_enc was removed from owner_secret_flags in #913"
    )
    assert "inline_key_enc" not in sig.parameters, "inline_key_enc was removed from owner_secret_flags in #913"
