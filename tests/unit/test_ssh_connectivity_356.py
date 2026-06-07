# tests/unit/test_ssh_connectivity_356.py
"""Unit tests for issue #356 — periodic SSH reachability probe.

Coverage:
- beat schedule entry present (schedule=900, correct task path)
- probe classification: TCP success + auth success → 1
- probe classification: TCP success + auth failure → 0
- probe classification: TCP failure → 0
- probe classification: exception → 0, sweep continues to next node
- redis writes: hset per minion_id, ts key written
- /metrics contract: gauge name literal present in metrics.py
- /metrics contract: main.py calls refresh from redis before generate_latest
"""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------


def test_beat_schedule_entry_present():
    from fleet_platform.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "check-ssh-connectivity" in schedule, "beat schedule missing 'check-ssh-connectivity'"
    entry = schedule["check-ssh-connectivity"]
    assert entry["schedule"] == 900, f"expected 900s, got {entry['schedule']}"
    assert entry["task"] == "fleet_platform.workers.connectivity_tasks.check_ssh_connectivity"
    assert entry.get("options", {}).get("queue") == "maintenance"


# ---------------------------------------------------------------------------
# Probe classification helpers
# ---------------------------------------------------------------------------


def _make_node(minion_id: str, ip: str = "192.168.1.10") -> MagicMock:
    node = MagicMock()
    node.minion_id = minion_id
    node.ip_address = ip
    return node


def _creds(auth_mode: str = "password", ssh_key: str = "") -> dict:
    return {
        "ssh_user": "admin",
        "ssh_password": "secret",
        "ssh_key": ssh_key,
        "auth_mode": auth_mode,
        "credential_source": "global",
    }


class _FakeSocket:
    """Fake socket that simulates TCP connect success or failure."""

    def __init__(self, succeed: bool = True):
        self._succeed = succeed

    def settimeout(self, t):
        pass

    def connect_ex(self, addr):
        return 0 if self._succeed else 111  # 0 = success, 111 = ECONNREFUSED

    def close(self):
        pass


def test_probe_tcp_and_auth_success_returns_1():
    """TCP connect succeeds + subprocess auth succeeds → 1."""
    from fleet_platform.workers.connectivity_tasks import _probe_node

    node = _make_node("mac-mini-01")
    creds = _creds(auth_mode="key", ssh_key="FAKE_KEY_MATERIAL")

    fake_proc = MagicMock()
    fake_proc.returncode = 0

    with (
        patch("fleet_platform.workers.connectivity_tasks.socket.socket", return_value=_FakeSocket(succeed=True)),
        patch("fleet_platform.workers.connectivity_tasks.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("fleet_platform.workers.connectivity_tasks.subprocess.run", return_value=fake_proc),
    ):
        # Simulate context manager for NamedTemporaryFile
        tmp_obj = MagicMock()
        tmp_obj.__enter__ = MagicMock(return_value=tmp_obj)
        tmp_obj.__exit__ = MagicMock(return_value=False)
        tmp_obj.name = "/tmp/fake_key"
        mock_tmp.return_value = tmp_obj

        result = _probe_node(node, creds)

    assert result == 1


def test_probe_tcp_success_auth_failure_returns_0():
    """TCP connect succeeds but subprocess returns non-zero (auth failure) → 0."""
    from fleet_platform.workers.connectivity_tasks import _probe_node

    node = _make_node("mac-mini-02")
    creds = _creds(auth_mode="key", ssh_key="FAKE_KEY_MATERIAL")

    fake_proc = MagicMock()
    fake_proc.returncode = 255  # SSH auth failure

    with (
        patch("fleet_platform.workers.connectivity_tasks.socket.socket", return_value=_FakeSocket(succeed=True)),
        patch("fleet_platform.workers.connectivity_tasks.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("fleet_platform.workers.connectivity_tasks.subprocess.run", return_value=fake_proc),
    ):
        tmp_obj = MagicMock()
        tmp_obj.__enter__ = MagicMock(return_value=tmp_obj)
        tmp_obj.__exit__ = MagicMock(return_value=False)
        tmp_obj.name = "/tmp/fake_key"
        mock_tmp.return_value = tmp_obj

        result = _probe_node(node, creds)

    assert result == 0


def test_probe_tcp_failure_returns_0():
    """TCP connect fails → 0, no SSH attempt."""
    from fleet_platform.workers.connectivity_tasks import _probe_node

    node = _make_node("mac-mini-03")
    creds = _creds(auth_mode="password")

    with patch("fleet_platform.workers.connectivity_tasks.socket.socket", return_value=_FakeSocket(succeed=False)):
        result = _probe_node(node, creds)

    assert result == 0


def test_probe_password_mode_tcp_success_returns_1():
    """Password auth mode: TCP connect only (no subprocess) → 1 on success."""
    from fleet_platform.workers.connectivity_tasks import _probe_node

    node = _make_node("mac-mini-04")
    creds = _creds(auth_mode="password", ssh_key="")  # no key → TCP-only check

    with patch("fleet_platform.workers.connectivity_tasks.socket.socket", return_value=_FakeSocket(succeed=True)):
        result = _probe_node(node, creds)

    assert result == 1


def test_probe_exception_returns_0():
    """If socket raises an exception, _probe_node returns 0 (never raises)."""
    from fleet_platform.workers.connectivity_tasks import _probe_node

    node = _make_node("mac-mini-05")
    creds = _creds()

    with patch("fleet_platform.workers.connectivity_tasks.socket.socket", side_effect=OSError("network error")):
        result = _probe_node(node, creds)

    assert result == 0


# ---------------------------------------------------------------------------
# Sweep — one bad node doesn't abort the rest
# ---------------------------------------------------------------------------


def test_sweep_continues_after_per_node_exception():
    """Exception in one node probe must not abort the sweep for remaining nodes."""
    from fleet_platform.workers.connectivity_tasks import check_ssh_connectivity

    node_a = _make_node("mac-mini-a", "10.0.0.1")
    node_b = _make_node("mac-mini-b", "10.0.0.2")
    node_c = _make_node("mac-mini-c", "10.0.0.3")

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node_a, node_b, node_c]

    creds_ok = _creds(auth_mode="password")

    mock_redis = MagicMock()

    call_count = 0

    def _resolve_side_effect(node, db):
        nonlocal call_count
        call_count += 1
        if node.minion_id == "mac-mini-b":
            raise RuntimeError("cred resolve blew up")
        return creds_ok

    def _probe_side_effect(node, creds):
        return 1

    with (
        patch("fleet_platform.workers.connectivity_tasks.get_sync_db", return_value=mock_db),
        patch(
            "fleet_platform.workers.connectivity_tasks.resolve_node_credentials_sync",
            side_effect=_resolve_side_effect,
        ),
        patch("fleet_platform.workers.connectivity_tasks._probe_node", side_effect=_probe_side_effect),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=mock_redis),
    ):
        result = check_ssh_connectivity()

    # node_b raised → 0 for it; node_a and node_c → 1 each; total 3 probed
    assert result["probed"] == 3
    assert result["reachable"] == 2
    assert result["unreachable"] == 1


# ---------------------------------------------------------------------------
# Redis writes
# ---------------------------------------------------------------------------


def test_redis_hset_written_per_minion():
    """check_ssh_connectivity must write hset per minion_id to kri:ssh_reachable."""
    from fleet_platform.workers.connectivity_tasks import check_ssh_connectivity

    node1 = _make_node("mac-mini-r1", "10.0.1.1")
    node2 = _make_node("mac-mini-r2", "10.0.1.2")

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node1, node2]

    mock_redis = MagicMock()

    with (
        patch("fleet_platform.workers.connectivity_tasks.get_sync_db", return_value=mock_db),
        patch(
            "fleet_platform.workers.connectivity_tasks.resolve_node_credentials_sync",
            return_value=_creds(auth_mode="password"),
        ),
        patch("fleet_platform.workers.connectivity_tasks._probe_node", return_value=1),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=mock_redis),
    ):
        check_ssh_connectivity()

    # hset must be called for each minion_id
    hset_calls = [c for c in mock_redis.hset.call_args_list]
    # We expect hset("kri:ssh_reachable", "mac-mini-r1", "1") and ("mac-mini-r2", "1")
    assert any("mac-mini-r1" in str(c) for c in hset_calls), "hset not called for mac-mini-r1"
    assert any("mac-mini-r2" in str(c) for c in hset_calls), "hset not called for mac-mini-r2"


def test_redis_ts_key_written():
    """check_ssh_connectivity must write kri:ssh_reachable:ts after sweep."""
    from fleet_platform.workers.connectivity_tasks import check_ssh_connectivity

    node = _make_node("mac-mini-ts", "10.0.2.1")

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node]

    mock_redis = MagicMock()

    with (
        patch("fleet_platform.workers.connectivity_tasks.get_sync_db", return_value=mock_db),
        patch(
            "fleet_platform.workers.connectivity_tasks.resolve_node_credentials_sync",
            return_value=_creds(auth_mode="password"),
        ),
        patch("fleet_platform.workers.connectivity_tasks._probe_node", return_value=1),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=mock_redis),
    ):
        check_ssh_connectivity()

    # set must be called for the timestamp key
    set_calls = [str(c) for c in mock_redis.set.call_args_list]
    assert any("kri:ssh_reachable:ts" in s for s in set_calls), (
        f"kri:ssh_reachable:ts not written. set calls: {set_calls}"
    )


def test_redis_failure_doesnt_raise():
    """If redis is unavailable, check_ssh_connectivity must still return a result."""
    from fleet_platform.workers.connectivity_tasks import check_ssh_connectivity

    node = _make_node("mac-mini-nored", "10.0.3.1")

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node]

    with (
        patch("fleet_platform.workers.connectivity_tasks.get_sync_db", return_value=mock_db),
        patch(
            "fleet_platform.workers.connectivity_tasks.resolve_node_credentials_sync",
            return_value=_creds(auth_mode="password"),
        ),
        patch("fleet_platform.workers.connectivity_tasks._probe_node", return_value=0),
        patch(
            "fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url",
            side_effect=ConnectionError("redis down"),
        ),
    ):
        result = check_ssh_connectivity()  # must not raise

    assert "probed" in result


# ---------------------------------------------------------------------------
# /metrics contract — gauge defined and refresh hooked into main.py
# ---------------------------------------------------------------------------


def test_gauge_name_defined_in_metrics_module():
    """kri_node_ssh_reachable Gauge must be registered in fleet_platform.metrics."""
    import fleet_platform.metrics as m

    assert hasattr(m, "node_ssh_reachable"), "fleet_platform.metrics is missing the 'node_ssh_reachable' Gauge object"
    # Confirm it's a Gauge-type metric (has labels method)
    assert callable(getattr(m.node_ssh_reachable, "labels", None)), "node_ssh_reachable is not a labelled Gauge"


def test_metrics_endpoint_refreshes_ssh_gauge():
    """main.py /metrics endpoint must refresh SSH (and all other) gauges before generate_latest.

    Updated (#576): refresh_ssh_reachability_gauge is now called internally by
    refresh_all_gauges, which is the single entry point used by the /metrics handler.
    """
    import pathlib

    src = (pathlib.Path(__file__).parent.parent.parent / "fleet_platform/api/main.py").read_text()
    # refresh_all_gauges delegates to refresh_ssh_reachability_gauge — verify the wrapper is called
    assert "refresh_all_gauges" in src, (
        "main.py /metrics handler must call refresh_all_gauges() which includes SSH gauge refresh (#576)"
    )
    # The SSH helper itself must still exist in metrics_collectors
    from fleet_platform.api.metrics_collectors import refresh_ssh_reachability_gauge  # noqa: F401

    assert callable(refresh_ssh_reachability_gauge)


def test_metrics_endpoint_imports_refresh():
    """The refresh function must be importable (i.e., module has no syntax errors)."""
    from fleet_platform.api.metrics_collectors import refresh_ssh_reachability_gauge  # noqa: F401

    assert callable(refresh_ssh_reachability_gauge)
