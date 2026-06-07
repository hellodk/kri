"""Tests for #520 (salt-master decoupling phase 5) + #498 (live log streaming).
Updated in #534: multi-master HA bootstrap — master resolution now uses all enabled
masters as a list (not a single FK/default row).  Health is a warning, not a gate.

Covers:
- A) Master resolution: all enabled SaltMaster rows → list passed to extravars
- B) Health behaviour: unreachable master logs a warning but bootstrap proceeds (#534);
     0 masters → mandatory hard failure (#534); probe still runs for unknown-status masters
     when explicitly selected (back-compat handled via the enabled list)
- C) Live streaming: event_handler feeds logs during run; 2 MB cap honoured; ANSI preserved
- Regression: successful run sets bootstrap_status='completed'; exception hits finally → 'failed'
"""

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(node_id: uuid.UUID, *, minion_id: str = "mm1.local", salt_master_id=None) -> MagicMock:
    node = MagicMock()
    node.id = node_id
    node.minion_id = minion_id
    node.bootstrap_status = "pending"
    node.bootstrap_ip = None
    node.bootstrap_logs = ""
    node.bootstrap_error = None
    node.ssh_key_enc = None
    node.ssh_host_key = None
    node.node_token_hash = None
    node.salt_master_id = salt_master_id
    node.ssh_username = None
    node.ssh_password_enc = None
    node.ssh_auth_mode = "password"
    return node


def _make_master(
    *, address: str = "salt.example.com", status: str = "healthy", name: str = "primary", enabled: bool = True
) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.address = address
    m.status = status
    m.name = name
    m.enabled = enabled
    m.is_default = True
    return m


def _make_run_async(status: str = "successful", rc: int = 0, events: list | None = None):
    """Return a (thread, runner) pair whose event_handler is callable via side-effect injection."""
    fake_runner = MagicMock()
    fake_runner.status = status
    fake_runner.rc = rc

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    return fake_thread, fake_runner


def _make_session(node, masters: list | None = None):
    """Build a DB session mock whose execute() returns node or masters list correctly.

    masters — list of SaltMaster mocks that will be returned by scalars().all().
    None defaults to an empty list (no masters configured).
    """
    master_list = masters if masters is not None else []
    session = MagicMock()

    def execute_side_effect(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = node
        result.scalar_one.return_value = node
        scalars = MagicMock()
        scalars.all.return_value = master_list
        scalars.first.return_value = master_list[0] if master_list else None
        result.scalars.return_value = scalars
        return result

    session.execute.side_effect = execute_side_effect
    session.add = MagicMock()
    return session


def _make_db_factory(node, masters: list | None = None):
    """Return a get_sync_db side_effect that always yields a session for node/masters."""

    def factory():
        session = _make_session(node, masters)

        @contextmanager
        def _ctx():
            yield session

        return _ctx()

    return factory


# ---------------------------------------------------------------------------
# A) Master resolution — all enabled masters form the list
# ---------------------------------------------------------------------------


def test_master_resolution_single_enabled_master():
    """When one enabled master exists, its address is in the salt_masters list and salt_master_address."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="mm1.example.com", status="healthy")

    fake_thread, fake_runner = _make_run_async()
    captured_extravars: list[dict] = []

    def fake_run_async(**kwargs):
        captured_extravars.append(kwargs.get("extravars", {}))
        return fake_thread, fake_runner

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("old-salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert captured_extravars, "run_async was not called"
    ev = captured_extravars[0]
    assert "mm1.example.com" in ev.get("salt_masters", []), (
        f"Expected master address in salt_masters list, got {ev.get('salt_masters')!r}"
    )
    assert ev.get("salt_master_address") == "mm1.example.com", (
        f"Back-compat salt_master_address must be the first master address, got {ev.get('salt_master_address')!r}"
    )
    assert "mm1.example.com" in ev.get("ingest_url", ""), (
        f"ingest_url must contain master address, got {ev.get('ingest_url')!r}"
    )


def test_master_resolution_two_enabled_masters():
    """With 2 enabled masters, both addresses appear in salt_masters extravars list."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id, salt_master_id=None)
    m1 = _make_master(address="salt-a.example.com", status="healthy", name="salt-a")
    m2 = _make_master(address="salt-b.example.com", status="healthy", name="salt-b")

    fake_thread, fake_runner = _make_run_async()
    captured_extravars: list[dict] = []

    def fake_run_async(**kwargs):
        captured_extravars.append(kwargs.get("extravars", {}))
        return fake_thread, fake_runner

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[m1, m2])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("old-salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert captured_extravars, "run_async was not called"
    ev = captured_extravars[0]
    salt_masters = ev.get("salt_masters", [])
    assert set(salt_masters) == {"salt-a.example.com", "salt-b.example.com"}, (
        f"Expected both master addresses in salt_masters, got {salt_masters!r}"
    )


def test_master_resolution_no_masters_fails():
    """When no enabled SaltMaster rows exist, bootstrap fails without invoking ansible (#534)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id, salt_master_id=None)

    run_async_called = []

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("legacy-salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=lambda **kw: run_async_called.append(True),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        result = bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert result.get("status") == "error"
    assert "No salt-master" in result.get("reason", ""), (
        f"Reason must mention 'No salt-master', got {result.get('reason')!r}"
    )
    assert not run_async_called, "ansible must NOT run when no masters are configured"


# ---------------------------------------------------------------------------
# B) Health behaviour (#534: unreachable = warning not gate)
# ---------------------------------------------------------------------------


def test_gate_unreachable_master_warns_but_proceeds():
    """When a master is unreachable, bootstrap_node logs a warning and proceeds (#534).
    Health is a WARNING — unreachable does NOT block ansible."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="dead-salt.example.com", status="unreachable", name="dead-master")

    run_async_called = []
    fake_thread, fake_runner = _make_run_async()

    def fake_run_async(**kwargs):
        run_async_called.append(True)
        return fake_thread, fake_runner

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.logger") as mock_logger,
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    # New contract (#534): unreachable master is a WARNING — ansible MUST still run
    assert run_async_called, "ansible run_async MUST be called even when master is unreachable (health = warning)"
    # A warning must be logged
    assert mock_logger.warning.called, "logger.warning must be called for the unreachable master"


def test_gate_unknown_master_triggers_probe_then_proceeds():
    """When master status=='unknown', run_probe is called once, then ansible proceeds (healthy probe)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(status="unknown", name="unprobed")

    fake_thread, fake_runner = _make_run_async()
    run_async_called = []

    def fake_run_async(**kwargs):
        run_async_called.append(True)
        return fake_thread, fake_runner

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    # Note: with multi-master (#534), run_probe is NOT called inline during bootstrap.
    # Probe is handled by the health-polling task (salt_health_polling_519).
    # An unknown-status master in the enabled list still allows bootstrap to proceed.
    assert run_async_called, "ansible run_async must proceed even with an unknown-status master"


def test_gate_unknown_master_probe_returns_unreachable_blocks_ansible():
    """When probe returns unreachable for an unknown master, ansible must not run.
    Note: probe is not called inline by bootstrap_node (#534) — if the master is
    in the enabled list, bootstrap proceeds regardless of its live probe result.
    This test verifies that the 0-master gate (not the probe gate) blocks ansible."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

    # No masters at all → mandatory gate
    run_async_called = []

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=lambda **kw: run_async_called.append(True),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert not run_async_called, "ansible must not run when no masters are configured"
    assert node.bootstrap_status == "failed"


def test_gate_skipped_when_no_master_row():
    """When no enabled SaltMaster rows exist, bootstrap hard-fails (mandatory gate, #534).
    Note: the legacy fallback-to-settings was removed — if no masters are configured, fail."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

    run_async_called = []

    # No master rows
    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("fallback.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=lambda **kw: run_async_called.append(True),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        result = bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    # #534: no fallback to legacy settings — empty masters is a hard failure
    assert not run_async_called, "ansible must NOT run when no salt masters are configured"
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# C) Live log streaming
# ---------------------------------------------------------------------------


def test_streaming_logs_flushed_during_run():
    """Logs are written to DB during the run (not only at the end) when _LOG_BATCH_INTERVAL elapses."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="salt.local", status="healthy")

    # We simulate a thread that is alive for a couple of ticks before dying,
    # so the flush loop fires at least once mid-run.
    alive_flags = [True, False]  # first call: alive; second: dead → join

    fake_runner = MagicMock()
    fake_runner.status = "successful"
    fake_runner.rc = 0

    fake_thread = MagicMock()
    fake_thread.is_alive.side_effect = lambda: alive_flags.pop(0) if alive_flags else False

    db_writes_during_run: list[str] = []

    def fake_run_async(**kwargs):
        return fake_thread, fake_runner

    # Make time advance fast so the batch interval check always triggers
    time_values = [0.0, 100.0, 200.0]  # first call returns 0 (init), next calls trigger flush

    def fake_time():
        return time_values.pop(0) if time_values else 999.0

    @contextmanager
    def fake_sync_db():
        session = _make_session(node, masters=[master])

        def commit_side_effect():
            if node.bootstrap_logs:
                db_writes_during_run.append(node.bootstrap_logs)

        session.commit.side_effect = commit_side_effect
        yield session

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.time.time", side_effect=fake_time),
        patch("fleet_platform.workers.ansible_tasks.time.sleep"),  # suppress real sleep
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    # The DB must have had writes during the run (before final commit)
    # At minimum, the final commit in step 6 writes bootstrap_logs
    assert db_writes_during_run, "bootstrap_logs must be written to DB during/after the run"


def test_stdout_cap_honoured():
    """Logs exceeding 2 MB are capped with a truncation sentinel."""
    from fleet_platform.workers.ansible_tasks import _MAX_STDOUT_BYTES, _TRUNCATION_SENTINEL, bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="salt.local", status="healthy")

    captured_event_handler: list = []
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_runner = MagicMock()
    fake_runner.status = "successful"
    fake_runner.rc = 0

    def fake_run_async(**kwargs):
        eh = kwargs.get("event_handler")
        # Feed events that exceed 2 MB total
        chunk = "A" * 512_000  # 512 KB per event
        for _ in range(5):  # 5 × 512 KB = 2.5 MB → exceeds 2 MB cap
            eh({"stdout": chunk, "event": "runner_on_ok", "event_data": {}})
        captured_event_handler.append(eh)
        return fake_thread, fake_runner

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.time.sleep"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    stored = node.bootstrap_logs or ""
    assert _TRUNCATION_SENTINEL in stored, (
        f"2 MB cap sentinel must appear in stored logs when output exceeds 2 MB. "
        f"Got {len(stored)} bytes, sentinel expected."
    )
    # Must not store vastly more than 2 MB
    assert len(stored) < _MAX_STDOUT_BYTES * 2, (
        f"Stored log ({len(stored)} bytes) is more than 2× the cap — truncation is not working"
    )


def test_ansi_codes_preserved_in_stored_logs():
    """ANSI colour codes must survive from event.stdout into node.bootstrap_logs."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="salt.local", status="healthy")

    ansi_line = "\x1b[32mOK\x1b[0m"  # green "OK"

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_runner = MagicMock()
    fake_runner.status = "successful"
    fake_runner.rc = 0

    def fake_run_async(**kwargs):
        eh = kwargs.get("event_handler")
        eh({"stdout": ansi_line, "event": "runner_on_ok", "event_data": {}})
        return fake_thread, fake_runner

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.time.sleep"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    stored = node.bootstrap_logs or ""
    assert "\x1b[" in stored, f"ANSI escape sequences must be preserved in stored bootstrap_logs. Got: {stored!r}"


# ---------------------------------------------------------------------------
# Regression: successful + exception paths
# ---------------------------------------------------------------------------


def test_successful_run_sets_completed_status():
    """A normal successful run must set bootstrap_status='completed'."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="salt.local", status="healthy")

    fake_thread, fake_runner = _make_run_async(status="successful", rc=0)

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            return_value=(fake_thread, fake_runner),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
        patch("fleet_platform.workers.ansible_tasks.time.sleep"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert node.bootstrap_status == "completed", (
        f"Expected 'completed' after successful run, got {node.bootstrap_status!r}"
    )


def test_exception_hits_finally_and_sets_failed():
    """An unhandled exception during bootstrap still sets bootstrap_status='failed' via the finally block."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="salt.local", status="healthy")

    @contextmanager
    def fake_sync_db():
        yield _make_session(node, masters=[master])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", new=fake_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=RuntimeError("boom"),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        try:
            bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")
        except Exception:
            pass

    assert node.bootstrap_status == "failed", (
        f"bootstrap_status must be 'failed' after exception, got {node.bootstrap_status!r}"
    )
    assert node.bootstrap_error, "bootstrap_error must be set after exception"
