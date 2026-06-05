# tests/unit/test_health_db_session_b20.py
"""
Tests for #124: collect_fleet_health must close the DB session before making
any Salt subprocess calls, so the connection pool slot is not held for the
entire (potentially 30s+) Salt collection window.
"""

import uuid
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(minion_id: str):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = minion_id
    return node


def _fake_metrics(*minion_ids: str) -> dict:
    return {
        mid: {
            "disk_root_used_gb": 50.0,
            "disk_root_total_gb": 256.0,
            "disk_root_pct": 20,
            "disk_root_inodes_pct": 1,
            "mem_total_gb": 16.0,
            "mem_available_gb": 8.0,
            "mem_used_pct": 50,
            "cpu_load_1m": 0.5,
            "cpu_load_5m": 0.4,
            "cpu_load_15m": 0.3,
            "uptime_seconds": 86400,
            "gpu_name": None,
            "gpu_vram_mb": None,
            "cpu_power_mw": None,
            "gpu_power_mw": None,
            "thermal_pressure": None,
            "error": None,
        }
        for mid in minion_ids
    }


# ---------------------------------------------------------------------------
# Test 1: Session 1 is CLOSED before collect_all_metrics is called
# ---------------------------------------------------------------------------


def test_collect_fleet_health_closes_session_before_salt_calls():
    """Session 1 must be fully closed (exited) before Salt metric collection."""
    from fleet_platform.workers.health_tasks import collect_fleet_health

    session_1_exited_before_salt = []  # mutable flag captured in closure

    # Track whether session 1's __exit__ has been called when Salt runs
    session_1_exit_called = [False]

    class _TrackingSession:
        """Context manager that records when it is exited."""

        def __init__(self):
            self.mock = MagicMock()

        def __enter__(self):
            return self.mock

        def __exit__(self, *args):
            session_1_exit_called[0] = True
            return False

    class _WriteSession:
        def __init__(self):
            self.mock = MagicMock()

        def __enter__(self):
            return self.mock

        def __exit__(self, *args):
            return False

    read_session = _TrackingSession()
    write_session = _WriteSession()

    node = _make_node("mac-mini-01")
    read_session.mock.execute.return_value.scalars.return_value.all.return_value = [node]

    call_count = [0]

    def fake_get_sync_db():
        call_count[0] += 1
        if call_count[0] == 1:
            return read_session
        return write_session

    def fake_collect_all_metrics(batch):
        # Record whether session 1 was already exited at the time Salt is called
        session_1_exited_before_salt.append(session_1_exit_called[0])
        return _fake_metrics(*batch)

    with (
        patch("fleet_platform.workers.health_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.health_tasks.salt_maintenance_svc.collect_all_metrics",
            side_effect=fake_collect_all_metrics,
        ),
    ):
        result = collect_fleet_health()

    assert result == {"collected": 1}
    # Salt was called at least once
    assert len(session_1_exited_before_salt) >= 1, "collect_all_metrics was never called"
    # Session 1 must have been closed before every Salt call
    assert all(session_1_exited_before_salt), (
        "Session 1 was still open when collect_all_metrics was called — "
        "this holds a connection pool slot during the entire Salt run"
    )


# ---------------------------------------------------------------------------
# Test 2: Exactly 2 DB sessions when nodes exist
# ---------------------------------------------------------------------------


def test_collect_fleet_health_uses_two_sessions():
    """When online nodes are found, exactly 2 get_sync_db() calls must be made."""
    from fleet_platform.workers.health_tasks import collect_fleet_health

    node = _make_node("mac-mini-01")

    read_mock = MagicMock()
    read_mock.__enter__ = MagicMock(return_value=read_mock)
    read_mock.__exit__ = MagicMock(return_value=False)
    read_mock.execute.return_value.scalars.return_value.all.return_value = [node]

    write_mock = MagicMock()
    write_mock.__enter__ = MagicMock(return_value=write_mock)
    write_mock.__exit__ = MagicMock(return_value=False)

    sessions = [read_mock, write_mock]
    call_count = [0]

    def fake_get_sync_db():
        idx = call_count[0]
        call_count[0] += 1
        return sessions[idx]

    with (
        patch("fleet_platform.workers.health_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.health_tasks.salt_maintenance_svc.collect_all_metrics",
            return_value=_fake_metrics("mac-mini-01"),
        ),
    ):
        result = collect_fleet_health()

    assert result == {"collected": 1}
    assert call_count[0] == 2, f"Expected exactly 2 DB sessions (read + write), got {call_count[0]}"
    # Read session should NOT have db.add called on it
    read_mock.add.assert_not_called()
    # Write session should have db.add called once and db.commit once
    write_mock.add.assert_called_once()
    write_mock.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: Early return (no online nodes) uses exactly 1 session
# ---------------------------------------------------------------------------


def test_collect_fleet_health_no_nodes_uses_one_session():
    """When there are no online nodes, only 1 DB session is opened (early return)."""
    from fleet_platform.workers.health_tasks import collect_fleet_health

    read_mock = MagicMock()
    read_mock.__enter__ = MagicMock(return_value=read_mock)
    read_mock.__exit__ = MagicMock(return_value=False)
    read_mock.execute.return_value.scalars.return_value.all.return_value = []

    call_count = [0]

    def fake_get_sync_db():
        call_count[0] += 1
        return read_mock

    with patch("fleet_platform.workers.health_tasks.get_sync_db", side_effect=fake_get_sync_db):
        result = collect_fleet_health()

    assert result == {"collected": 0}
    assert call_count[0] == 1, f"Expected exactly 1 DB session for no-nodes early return, got {call_count[0]}"
