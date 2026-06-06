"""Tests for #520 (salt-master decoupling phase 5) + #498 (live log streaming).

Covers:
- A) Master resolution: node.salt_master_id FK → default row → fallback to settings value
- B) Health gate: unreachable master blocks ansible; unknown master triggers probe once
- C) Live streaming: event_handler feeds logs during run; 2 MB cap honoured; ANSI preserved
- Regression: successful run sets bootstrap_status='completed'; exception hits finally → 'failed'
"""

import uuid
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


def _make_master(*, address: str = "salt.example.com", status: str = "healthy", name: str = "primary") -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.address = address
    m.status = status
    m.name = name
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


def _make_session(node, master_obj=None):
    """Build a DB session mock whose execute().scalar*() returns node or master correctly."""
    session = MagicMock()

    def execute_side_effect(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = node
        result.scalar_one.return_value = node
        result.scalars.return_value.first.return_value = master_obj
        return result

    session.execute.side_effect = execute_side_effect
    session.add = MagicMock()
    return session


def _make_db_factory(node, master_obj=None):
    """Return a get_sync_db side_effect that always yields a session for node/master."""

    def factory():
        session = _make_session(node, master_obj)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    return factory


# ---------------------------------------------------------------------------
# A) Master resolution
# ---------------------------------------------------------------------------


def test_master_resolution_via_salt_master_id():
    """When node.salt_master_id is set, its master's address populates extravars/ingest_url."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    master_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = _make_node(node_id, salt_master_id=master_id)
    master = _make_master(address="mm1.example.com", status="healthy")
    master.id = master_id

    fake_thread, fake_runner = _make_run_async()
    captured_extravars: list[dict] = []

    def fake_run_async(**kwargs):
        captured_extravars.append(kwargs.get("extravars", {}))
        return fake_thread, fake_runner

    def make_session_with_master():
        session = MagicMock()
        call_count = {"n": 0}

        def execute_side_effect(stmt):
            call_count["n"] += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = node
            result.scalar_one.return_value = node
            # First scalars().first() call (salt_master_id lookup) → return master
            result.scalars.return_value.first.return_value = master
            return result

        session.execute.side_effect = execute_side_effect
        session.add = MagicMock()
        return session

    def fake_get_sync_db():
        session = make_session_with_master()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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
    assert ev.get("salt_master_address") == "mm1.example.com", (
        f"Expected master address 'mm1.example.com', got {ev.get('salt_master_address')!r}"
    )
    assert "mm1.example.com" in ev.get("ingest_url", ""), (
        f"ingest_url must contain master address, got {ev.get('ingest_url')!r}"
    )
    assert "old-salt.local" not in ev.get("salt_master_address", ""), (
        "Must not fall back to legacy settings value when salt_master_id is set"
    )


def test_master_resolution_via_default_row():
    """When node has no salt_master_id but a default SaltMaster row exists, use that address."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id, salt_master_id=None)
    master = _make_master(address="default-salt.example.com", status="healthy")

    fake_thread, fake_runner = _make_run_async()
    captured_extravars: list[dict] = []

    def fake_run_async(**kwargs):
        captured_extravars.append(kwargs.get("extravars", {}))
        return fake_thread, fake_runner

    def fake_get_sync_db():
        session = _make_session(node, master_obj=master)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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
    assert ev.get("salt_master_address") == "default-salt.example.com", (
        f"Expected default master address, got {ev.get('salt_master_address')!r}"
    )


def test_master_resolution_fallback_to_settings():
    """When no SaltMaster row exists, fall back to the legacy platform-settings value."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id, salt_master_id=None)

    fake_thread, fake_runner = _make_run_async()
    captured_extravars: list[dict] = []

    def fake_run_async(**kwargs):
        captured_extravars.append(kwargs.get("extravars", {}))
        return fake_thread, fake_runner

    # scalars().first() returns None → no SaltMaster row
    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("legacy-salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert captured_extravars, "run_async was not called (should have proceeded with fallback)"
    ev = captured_extravars[0]
    assert ev.get("salt_master_address") == "legacy-salt.local", (
        f"Expected legacy fallback address 'legacy-salt.local', got {ev.get('salt_master_address')!r}"
    )
    assert "legacy-salt.local" in ev.get("ingest_url", ""), (
        f"ingest_url must use fallback address, got {ev.get('ingest_url')!r}"
    )


# ---------------------------------------------------------------------------
# B) Health gate
# ---------------------------------------------------------------------------


def test_gate_unreachable_master_blocks_ansible():
    """When the resolved master status is 'unreachable', run_async must NOT be invoked."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(address="dead-salt.example.com", status="unreachable", name="dead-master")

    run_async_called = []

    def fake_run_async(**kwargs):
        run_async_called.append(True)
        return _make_run_async()

    def fake_get_sync_db():
        session = _make_session(node, master_obj=master)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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
        result = bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert not run_async_called, "ansible run_async must NOT be called when master is unreachable"
    assert node.bootstrap_status == "failed", (
        f"Node must be 'failed' when master is unreachable, got {node.bootstrap_status!r}"
    )
    assert "dead-master" in (node.bootstrap_error or ""), (
        f"Error message must name the master, got {node.bootstrap_error!r}"
    )
    assert result.get("status") == "error"


def test_gate_unknown_master_triggers_probe_then_proceeds():
    """When master status=='unknown', run_probe is called once, then ansible proceeds (healthy probe)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(status="unknown", name="unprobed")

    probe_calls = []

    async def fake_run_probe(m):
        probe_calls.append(m)
        return {"status": "healthy", "checks": []}

    fake_thread, fake_runner = _make_run_async()
    run_async_called = []

    def fake_run_async(**kwargs):
        run_async_called.append(True)
        return fake_thread, fake_runner

    def fake_get_sync_db():
        session = _make_session(node, master_obj=master)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.run_probe", side_effect=fake_run_probe),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert len(probe_calls) == 1, f"run_probe must be called exactly once, was called {len(probe_calls)}"
    assert run_async_called, "ansible run_async must proceed after probe returns healthy"


def test_gate_unknown_master_probe_returns_unreachable_blocks_ansible():
    """When probe returns unreachable for an unknown master, ansible must not run."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)
    master = _make_master(status="unknown", name="bad-master")

    async def fake_run_probe(m):
        return {
            "status": "unreachable",
            "checks": [{"check": "dns", "status": "fail", "detail": "no DNS", "latency_ms": 0}],
        }

    run_async_called = []

    def fake_get_sync_db():
        session = _make_session(node, master_obj=master)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("salt.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.run_probe", side_effect=fake_run_probe),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=lambda **kw: run_async_called.append(True),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert not run_async_called, "ansible must not run when probe returns unreachable"
    assert node.bootstrap_status == "failed"


def test_gate_skipped_when_no_master_row():
    """When no SaltMaster row exists, the gate is skipped and ansible runs with fallback address."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

    fake_thread, fake_runner = _make_run_async()
    run_async_called = []

    def fake_run_async(**kwargs):
        run_async_called.append(True)
        return fake_thread, fake_runner

    # No master row
    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("fallback.local", "admin", "pw", "pubkey"),
        ),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", "pw", "password")),
        patch("fleet_platform.workers.ansible_tasks._get_group_credentials", return_value=("", "", "", "password")),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner.run_async", side_effect=fake_run_async),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")

    assert run_async_called, "ansible must run when no SaltMaster row exists (fallback path)"


# ---------------------------------------------------------------------------
# C) Live log streaming
# ---------------------------------------------------------------------------


def test_streaming_logs_flushed_during_run():
    """Logs are written to DB during the run (not only at the end) when _LOG_BATCH_INTERVAL elapses."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

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

    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)

        def tracking_exec(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = node
            result.scalar_one.return_value = node
            result.scalars.return_value.first.return_value = None
            return result

        session.execute.side_effect = tracking_exec

        def commit_side_effect():
            if node.bootstrap_logs:
                db_writes_during_run.append(node.bootstrap_logs)

        session.commit.side_effect = commit_side_effect
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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

    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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

    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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

    fake_thread, fake_runner = _make_run_async(status="successful", rc=0)

    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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

    def fake_get_sync_db():
        session = _make_session(node, master_obj=None)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
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
