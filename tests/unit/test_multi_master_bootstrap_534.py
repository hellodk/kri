# tests/unit/test_multi_master_bootstrap_534.py
# Issue #534 — multi-master HA bootstrap (failover master list + mandatory gate + health warn)
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_master(address: str, status: str = "healthy", enabled: bool = True, name: str = "") -> MagicMock:
    m = MagicMock(spec=[])
    m.id = uuid.uuid4()
    m.address = address
    m.status = status
    m.name = name or address
    m.enabled = enabled
    # Disable auto-accept in existing multi-master tests — they don't test that path
    # and don't set up db.execute calls for the extra key.accept log writes.
    m.auto_accept = False
    return m


def _make_node(minion_id: str = "mm1") -> MagicMock:
    n = MagicMock(spec=[])
    n.id = uuid.uuid4()
    n.minion_id = minion_id
    n.bootstrap_status = "pending"
    n.bootstrap_ip = None
    n.bootstrap_logs = ""
    n.bootstrap_error = None
    n.ssh_username = "admin"
    n.ssh_password_enc = None
    n.ssh_auth_mode = "password"
    n.ssh_key_enc = None
    n.node_token_hash = None
    n.salt_master_id = None
    n.ssh_host_key = None
    return n


def _make_db_ctx(execute_side_effects):
    """Context-manager mock that forwards execute() calls from the side_effects list."""
    db = MagicMock()
    db.execute.side_effect = execute_side_effects

    @contextmanager
    def _ctx():
        yield db

    return _ctx


def _node_execute_result(node):
    r = MagicMock()
    r.scalar_one_or_none.return_value = node
    r.scalar_one.return_value = node
    return r


def _masters_execute_result(masters):
    r = MagicMock()
    s = MagicMock()
    s.all.return_value = masters
    s.first.return_value = masters[0] if masters else None
    r.scalars.return_value = s
    return r


def _run_execute_result(run_obj=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = run_obj
    return r


# ─── Test: 2 masters → salt_masters extravar is a LIST ────────────────────────


def test_two_masters_extravar_is_list_and_failover():
    """bootstrap_node with 2 enabled masters must pass salt_masters=[addr1, addr2]
    as the extravar, allowing the playbook to render a multi-master failover config (#534)."""
    m1 = _make_master("10.0.0.1")
    m2 = _make_master("10.0.0.2")
    node = _make_node()
    run_obj = MagicMock()
    run_obj.id = uuid.uuid4()

    # DB call sequence across multiple get_sync_db() contexts:
    # ctx1 (step 1): execute→node, execute→masters
    # ctx2 (step 3, token+run): execute→node
    # ctx3 (step 5, finalize): execute→node, execute→run
    # ctx4 (finally — only if step 6 didn't complete): not reached in success path
    calls = [
        _node_execute_result(node),  # step 1: load node
        _masters_execute_result([m1, m2]),  # step 1: load masters (enabled)
        _node_execute_result(node),  # step 3: update token
        _node_execute_result(node),  # step 5 finalize: load node
        _run_execute_result(run_obj),  # step 5 finalize: load BootstrapRun
    ]

    call_iter = iter(calls)

    db = MagicMock()
    db.execute.side_effect = lambda *a, **kw: next(call_iter)

    @contextmanager
    def _sync_db():
        yield db

    captured_extravars: dict = {}

    def _fake_run_async(private_data_dir, playbook, inventory, extravars, envvars, event_handler, **kwargs):
        captured_extravars.update(extravars)
        thread = MagicMock()
        thread.is_alive.return_value = False
        runner = MagicMock()
        runner.status = "successful"
        runner.rc = 0
        return thread, runner

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("", "admin", "secret", "")),
        patch(
            "fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "secret", "password")
        ),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "")),
        patch("ansible_runner.run_async", side_effect=_fake_run_async),
    ):
        from fleet_platform.workers.ansible_tasks import bootstrap_node

        bootstrap_node(str(node.id), "10.0.0.9")

    # Must have passed salt_masters as a list of both addresses
    assert "salt_masters" in captured_extravars, "salt_masters extravar must be present"
    assert set(captured_extravars["salt_masters"]) == {"10.0.0.1", "10.0.0.2"}, (
        f"Expected both master addresses, got {captured_extravars['salt_masters']}"
    )
    # Back-compat alias must be one of the master addresses
    assert captured_extravars["salt_master_address"] in ("10.0.0.1", "10.0.0.2"), (
        "salt_master_address back-compat alias must be set to the first master address"
    )


# ─── Test: 0 masters → refused, ansible NOT invoked ────────────────────────────


def test_zero_masters_refuses_bootstrap():
    """When no enabled SaltMaster rows exist, bootstrap_node must set node.bootstrap_status='failed'
    and return immediately without invoking ansible (#534)."""
    node = _make_node()

    calls = [
        _node_execute_result(node),  # step 1: load node
        _masters_execute_result([]),  # step 1: load enabled masters → empty
        _node_execute_result(node),  # mandatory-gate fail db: load node to set failed
        _run_execute_result(None),  # mandatory-gate fail db: look for orphan run
    ]
    call_iter = iter(calls)

    db = MagicMock()
    db.execute.side_effect = lambda *a, **kw: next(call_iter)

    @contextmanager
    def _sync_db():
        yield db

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("", "admin", "secret", "")),
        patch(
            "fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "secret", "password")
        ),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "")),
        patch("ansible_runner.run_async") as mock_run_async,
    ):
        from fleet_platform.workers.ansible_tasks import bootstrap_node

        result = bootstrap_node(str(node.id), "10.0.0.9")

    assert result["status"] == "error"
    assert "No salt-master" in result["reason"]
    # Ansible must NOT have been invoked
    mock_run_async.assert_not_called()


# ─── Test: unreachable master → WARNING logged but bootstrap proceeds ───────────


def test_unreachable_master_logs_warning_and_proceeds():
    """When a selected master has status='unreachable', bootstrap_node must log a warning
    but still invoke ansible_runner.run_async (health is a warning, not a gate) (#534)."""
    m1 = _make_master("10.0.0.1", status="unreachable", name="master-1")
    node = _make_node()
    run_obj = MagicMock()
    run_obj.id = uuid.uuid4()

    calls = [
        _node_execute_result(node),  # step 1: load node
        _masters_execute_result([m1]),  # step 1: load enabled masters
        _node_execute_result(node),  # step 3: update token
        _node_execute_result(node),  # step 5 finalize: load node
        _run_execute_result(run_obj),  # step 5 finalize: load BootstrapRun
    ]
    call_iter = iter(calls)

    db = MagicMock()
    db.execute.side_effect = lambda *a, **kw: next(call_iter)

    @contextmanager
    def _sync_db():
        yield db

    run_async_called = []

    def _fake_run_async(private_data_dir, playbook, inventory, extravars, envvars, event_handler, **kwargs):
        run_async_called.append(extravars)
        thread = MagicMock()
        thread.is_alive.return_value = False
        runner = MagicMock()
        runner.status = "successful"
        runner.rc = 0
        return thread, runner

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=_sync_db),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("", "admin", "secret", "")),
        patch(
            "fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "secret", "password")
        ),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "")),
        patch("ansible_runner.run_async", side_effect=_fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.logger") as mock_logger,
    ):
        from fleet_platform.workers.ansible_tasks import bootstrap_node

        bootstrap_node(str(node.id), "10.0.0.9")

    # ansible_runner.run_async MUST have been called (not blocked)
    assert len(run_async_called) == 1, "run_async must be invoked even with an unreachable master"
    # A warning must have been logged
    warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
    assert any("unreachable" in w.lower() or "master" in w.lower() for w in warning_calls), (
        "A warning about the unreachable master must be logged"
    )
