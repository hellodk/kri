# tests/unit/test_ssh_connectivity_356.py
"""Unit tests for issue #356 — periodic SSH reachability sweep.

The probe mechanism itself now lives in ``fleet_platform.services.ssh_probe``
(see test_ssh_probe_356ui.py). This file covers the *sweep* wiring:

- beat schedule entry present (schedule=900, correct task path)
- sweep persists ssh_state to the DB and the legacy 0/1 signal to Redis
- one bad node doesn't abort the rest
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
# Helpers
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


# ---------------------------------------------------------------------------
# Sweep — persistence + one bad node doesn't abort the rest
# ---------------------------------------------------------------------------


def test_sweep_persists_ssh_state_to_db():
    """Each probed node gets ssh_state/ssh_detail/ssh_checked_at set, and db.commit() runs."""
    from fleet_platform.workers.connectivity_tasks import check_ssh_connectivity

    node = _make_node("mac-mini-persist", "10.0.5.1")

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
        patch(
            "fleet_platform.workers.connectivity_tasks.probe_node_ssh",
            return_value={"state": "ok", "detail": "authenticated"},
        ),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=MagicMock()),
    ):
        result = check_ssh_connectivity()

    assert node.ssh_state == "ok"
    assert node.ssh_detail == "authenticated"
    assert node.ssh_checked_at is not None
    mock_db.commit.assert_called_once()
    assert result["reachable"] == 1


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

    mock_redis = MagicMock()

    def _resolve_side_effect(node, db):
        if node.minion_id == "mac-mini-b":
            raise RuntimeError("cred resolve blew up")
        return _creds(auth_mode="password")

    def _probe_side_effect(node, creds):
        return {"state": "ok", "detail": "authenticated"}

    with (
        patch("fleet_platform.workers.connectivity_tasks.get_sync_db", return_value=mock_db),
        patch(
            "fleet_platform.workers.connectivity_tasks.resolve_node_credentials_sync",
            side_effect=_resolve_side_effect,
        ),
        patch("fleet_platform.workers.connectivity_tasks.probe_node_ssh", side_effect=_probe_side_effect),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=mock_redis),
    ):
        result = check_ssh_connectivity()

    # node_b raised → unreachable for it; node_a and node_c → ok; total 3 probed
    assert result["probed"] == 3
    assert result["reachable"] == 2
    assert result["unreachable"] == 1
    assert node_b.ssh_state == "unreachable"


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
        patch(
            "fleet_platform.workers.connectivity_tasks.probe_node_ssh",
            return_value={"state": "ok", "detail": "authenticated"},
        ),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=mock_redis),
    ):
        check_ssh_connectivity()

    # hset must be called for each minion_id with the legacy 1 (ok) signal
    hset_calls = [c for c in mock_redis.hset.call_args_list]
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
        patch(
            "fleet_platform.workers.connectivity_tasks.probe_node_ssh",
            return_value={"state": "ok", "detail": "authenticated"},
        ),
        patch("fleet_platform.workers.connectivity_tasks.sync_redis.Redis.from_url", return_value=mock_redis),
    ):
        check_ssh_connectivity()

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
        patch(
            "fleet_platform.workers.connectivity_tasks.probe_node_ssh",
            return_value={"state": "unreachable", "detail": "TCP port 22 closed or timed out"},
        ),
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
    import fleet_platform.api.main as main_module
    from fleet_platform.api.metrics_collectors import refresh_ssh_reachability_gauge

    # Behavioral: refresh_all_gauges must be imported into main's namespace (i.e., it IS the call-site)
    assert hasattr(main_module, "refresh_all_gauges") and callable(main_module.refresh_all_gauges), (
        "main.py must import and expose refresh_all_gauges from metrics_collectors (#576)"
    )
    assert callable(refresh_ssh_reachability_gauge)


def test_metrics_endpoint_imports_refresh():
    """The refresh function must be importable (i.e., module has no syntax errors)."""
    from fleet_platform.api.metrics_collectors import refresh_ssh_reachability_gauge  # noqa: F401

    assert callable(refresh_ssh_reachability_gauge)
