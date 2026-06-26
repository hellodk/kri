# tests/unit/test_worker_credentials_913.py
"""Unit tests for #913: bootstrap_node resolves SSH credentials via resolve_node_credentials_sync.

Covers:
- Worker calls resolve_node_credentials_sync (not the old inline helpers)
- Per-run ssh_username argument overrides the resolved user
- Missing credentials (no password, no key) triggers a hard fail
"""

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESOLVED_CREDS_PASSWORD = {
    "ssh_user": "resolveduser",
    "ssh_password": "resolvedpw",
    "ssh_key": "",
    "auth_mode": "password",
    "credential_source": "node",
}

_RESOLVED_CREDS_KEY = {
    "ssh_user": "keyuser",
    "ssh_password": "",
    "ssh_key": "PRIVATE_KEY_BLOB",
    "auth_mode": "key",
    "credential_source": "group:prod",
}

_RESOLVED_CREDS_EMPTY = {
    "ssh_user": "admin",
    "ssh_password": "",
    "ssh_key": "",
    "auth_mode": "password",
    "credential_source": "global",
}


def _make_node(node_id: uuid.UUID) -> MagicMock:
    node = MagicMock()
    node.id = node_id
    node.minion_id = "test-node-01"
    node.bootstrap_status = "pending"
    node.bootstrap_ip = None
    node.bootstrap_logs = ""
    node.bootstrap_error = None
    node.ssh_host_key = None
    node.node_token_hash = None
    node.salt_master_id = None
    # credential_id is handled by the resolver mock, not the worker directly
    node.credential_id = None
    return node


def _make_master(address: str = "10.0.0.1") -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.address = address
    m.status = "healthy"
    m.name = "master-1"
    m.enabled = True
    m.auto_accept = False
    return m


def _build_db(node, master, run_obj):
    """Build a sync DB mock that returns the right objects for each execute() call."""
    db = MagicMock()
    call_results = []

    # Step 1: load node
    r_node1 = MagicMock()
    r_node1.scalar_one_or_none.return_value = node
    call_results.append(r_node1)

    # Step 1: load enabled masters
    r_masters = MagicMock()
    r_masters.scalars.return_value.all.return_value = [master]
    call_results.append(r_masters)

    # Step 3: update token
    r_node2 = MagicMock()
    r_node2.scalar_one.return_value = node
    call_results.append(r_node2)

    # Step 6 finalize: load node
    r_node3 = MagicMock()
    r_node3.scalar_one.return_value = node
    call_results.append(r_node3)

    # Step 6 finalize: load BootstrapRun
    r_run = MagicMock()
    r_run.scalar_one_or_none.return_value = run_obj
    call_results.append(r_run)

    call_iter = iter(call_results)
    db.execute.side_effect = lambda *a, **kw: next(call_iter)
    db.get.return_value = None
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bootstrap_node_uses_resolver_not_inline_helpers():
    """bootstrap_node must call resolve_node_credentials_sync for credential resolution (#913)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master()
    run_obj = MagicMock()
    run_obj.id = uuid.uuid4()
    db = _build_db(node, master, run_obj)

    @contextmanager
    def _sync_db():
        yield db

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_runner = MagicMock()
    fake_runner.status = "successful"
    fake_runner.rc = 0

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("admin", "pw", "pubkey")),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value=_RESOLVED_CREDS_PASSWORD,
        ) as mock_resolver,
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", return_value=(fake_thread, fake_runner)),
        patch("fleet_platform.workers.ansible_tasks.publish_job_event"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
    ):
        result = bootstrap_node(str(node_id), "10.0.0.9")

    assert result["status"] == "successful"
    # Resolver must have been called with the node and db
    mock_resolver.assert_called_once_with(node, db)


def test_per_run_ssh_username_overrides_resolved_user():
    """Per-run ssh_username argument takes priority over the resolved user (#913, req 2)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master()
    run_obj = MagicMock()
    run_obj.id = uuid.uuid4()
    db = _build_db(node, master, run_obj)

    captured_inventory: list[str] = []

    @contextmanager
    def _sync_db():
        yield db

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_runner = MagicMock()
    fake_runner.status = "successful"
    fake_runner.rc = 0

    def _capture_run_async(private_data_dir, playbook, inventory, extravars, envvars, event_handler, **kwargs):
        # Read the inventory file to verify the user that was used
        from pathlib import Path

        captured_inventory.append(Path(inventory).read_text())
        return fake_thread, fake_runner

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("admin", "pw", "pubkey")),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value=_RESOLVED_CREDS_PASSWORD,  # resolver says user="resolveduser"
        ),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=_capture_run_async),
        patch("fleet_platform.workers.ansible_tasks.publish_job_event"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
    ):
        bootstrap_node(str(node_id), "10.0.0.9", ssh_username="override-user")

    assert captured_inventory, "ansible_runner.run_async must have been invoked"
    inv = captured_inventory[0]
    assert "override-user" in inv, f"Per-run ssh_username must override the resolved user; got inventory:\n{inv}"
    assert "resolveduser" not in inv, "Resolved user must not appear when per-run override is given"


def test_missing_credentials_sets_failed_and_returns_error():
    """When resolver returns no password and no key, bootstrap_node must set
    bootstrap_status='failed' and return {status:'error'} without invoking ansible (#913, req 2)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master()
    # For the missing-creds path, we only need node load + masters load (no token/run step)
    db = MagicMock()
    call_results = []

    r_node1 = MagicMock()
    r_node1.scalar_one_or_none.return_value = node
    call_results.append(r_node1)

    r_masters = MagicMock()
    r_masters.scalars.return_value.all.return_value = [master]
    call_results.append(r_masters)

    call_iter = iter(call_results)
    db.execute.side_effect = lambda *a, **kw: next(call_iter)

    @contextmanager
    def _sync_db():
        yield db

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("admin", "", "pubkey")),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value=_RESOLVED_CREDS_EMPTY,  # no password, no key
        ),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async") as mock_run_async,
        patch("fleet_platform.workers.ansible_tasks.publish_job_event"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
    ):
        result = bootstrap_node(str(node_id), "10.0.0.9")

    assert result["status"] == "error", f"Expected status='error', got {result}"
    assert node.bootstrap_status == "failed", f"Expected bootstrap_status='failed', got {node.bootstrap_status}"
    assert node.bootstrap_error, "bootstrap_error must be set with a descriptive message"
    mock_run_async.assert_not_called()


def test_key_auth_resolver_result_written_to_key_file():
    """When resolver returns ssh_key (key auth), the key must be written to a temp file
    and passed via ansible_ssh_private_key_file in the inventory (#913)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master()
    run_obj = MagicMock()
    run_obj.id = uuid.uuid4()
    db = _build_db(node, master, run_obj)

    captured_inventory: list[str] = []

    @contextmanager
    def _sync_db():
        yield db

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_runner = MagicMock()
    fake_runner.status = "successful"
    fake_runner.rc = 0

    def _capture_run_async(private_data_dir, playbook, inventory, extravars, envvars, event_handler, **kwargs):
        from pathlib import Path

        captured_inventory.append(Path(inventory).read_text())
        return fake_thread, fake_runner

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("admin", "", "pubkey")),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value=_RESOLVED_CREDS_KEY,
        ),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=_capture_run_async),
        patch("fleet_platform.workers.ansible_tasks.publish_job_event"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
    ):
        result = bootstrap_node(str(node_id), "10.0.0.9")

    assert result["status"] == "successful"
    assert captured_inventory, "ansible_runner.run_async must have been invoked"
    inv = captured_inventory[0]
    assert "ansible_ssh_private_key_file=" in inv, "Key auth path must write key to file and reference it in inventory"
    assert "keyuser" in inv, "Resolved ssh_user from key credential must appear in inventory"
