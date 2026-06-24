"""Behavioral tests for fleet_platform/workers/maintenance.py (#809 TST-13).

Each test CALLS the actual task function with mocked DB/Redis/salt dependencies
and asserts on real return values, side effects, and branch paths — not source
strings.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bootstrap: stub missing infrastructure packages so maintenance.py can be
# imported in environments where broker / DB packages aren't installed.
#
# Strategy: attempt a real import first; only install a stub when the package
# genuinely cannot be found.  This ensures that when all packages ARE present
# (e.g. in the full uv venv or CI), the real modules are used and the stubs
# never pollute sys.modules for other test files.
# ---------------------------------------------------------------------------
import importlib
import sys
import types
import uuid
from unittest.mock import MagicMock, patch


def _ensure_importable(pkg_name: str) -> None:
    """Import *pkg_name* for real if available; otherwise insert a minimal stub.

    Calling this before importing any fleet_platform worker module guarantees
    that the import machinery can proceed even when infrastructure packages
    (redis, celery, …) are absent.  When a package IS available the real
    module is loaded into sys.modules — subsequent imports in the same process
    get the real thing, not a stub.
    """
    if pkg_name in sys.modules:
        return
    try:
        importlib.import_module(pkg_name)
    except ImportError:
        stub = types.ModuleType(pkg_name)
        stub.__spec__ = None  # type: ignore[attr-defined]
        sys.modules[pkg_name] = stub


for _pkg in [
    "redis",
    "redis.asyncio",
    "celery",
    "celery.schedules",
    "celery.signals",
    "celery.utils",
    "celery.utils.log",
    "redbeat",
    "redbeat.schedulers",
]:
    _ensure_importable(_pkg)

# Ensure redis.asyncio is reachable as an attribute of the redis module so
# that `import redis.asyncio as aioredis` works regardless of whether the
# stub or the real package ended up in sys.modules.
_redis_mod = sys.modules.get("redis")
if _redis_mod is not None and not hasattr(_redis_mod, "asyncio"):
    _redis_asyncio = sys.modules.get("redis.asyncio")
    if _redis_asyncio is not None:
        _redis_mod.asyncio = _redis_asyncio  # type: ignore[attr-defined]

# fleet_platform.db.session creates SQLAlchemy engines at module load time
# (requires psycopg).  When psycopg is unavailable, replace the module with a
# minimal stub so that maintenance.py can be imported.  When psycopg IS
# present the real module is used (no stub installed).
if "fleet_platform.db.session" not in sys.modules:
    try:
        importlib.import_module("fleet_platform.db.session")
    except Exception:
        _db_session_stub = types.ModuleType("fleet_platform.db.session")
        _db_session_stub.get_sync_db = MagicMock()  # type: ignore[attr-defined]
        sys.modules["fleet_platform.db.session"] = _db_session_stub

# fleet_platform.workers.celery_app creates the Celery app at module load
# time.  Provide a stub whose .task() decorator is a passthrough so that
# @celery_app.task(...) leaves the decorated function callable (not wrapped
# in a MagicMock Task object).  When celery IS available (e.g. CI), the real
# celery_app module is used and this stub is never installed.
if "fleet_platform.workers.celery_app" not in sys.modules:
    try:
        importlib.import_module("fleet_platform.workers.celery_app")
    except Exception:

        def _passthrough_task(*args, **kwargs):
            def _wrap(fn):
                fn.delay = MagicMock()
                fn.apply_async = MagicMock()
                return fn

            if len(args) == 1 and callable(args[0]):
                return _wrap(args[0])
            return _wrap

        _celery_app_obj = MagicMock()
        _celery_app_obj.task = _passthrough_task
        _celery_app_mod = types.ModuleType("fleet_platform.workers.celery_app")
        _celery_app_mod.celery_app = _celery_app_obj  # type: ignore[attr-defined]
        sys.modules["fleet_platform.workers.celery_app"] = _celery_app_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(execute_side_effects, *, commit_ok=True):
    """Return a context-manager-compatible fake DB session."""

    call_iter = iter(execute_side_effects)

    class _FakeSession:
        def execute(self, stmt):
            return next(call_iter)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _FakeSession()


def _rowcount_result(n: int):
    r = MagicMock()
    r.rowcount = n
    return r


def _select_scalars_result(values):
    class _R:
        def scalars(self):
            return self

        def all(self):
            return list(values)

    return _R()


# ---------------------------------------------------------------------------
# mark_stale_nodes
# ---------------------------------------------------------------------------


def test_mark_stale_nodes_returns_dict_with_stale_and_offline():
    from fleet_platform.workers.maintenance import mark_stale_nodes

    session = _make_session([_rowcount_result(4), _rowcount_result(2)])

    with (
        patch("fleet_platform.workers.maintenance.get_sync_db", return_value=session),
        patch("fleet_platform.workers.maintenance.get_setting_sync", return_value=None),
        patch("fleet_platform.workers.maintenance.sync_redis") as mock_redis,
    ):
        mock_redis.Redis.from_url.return_value = MagicMock()
        result = mark_stale_nodes()

    assert result == {"stale": 4, "offline": 2}


def test_mark_stale_nodes_falls_back_to_defaults_on_invalid_setting():
    """get_setting_sync returning non-integer must not raise; defaults are used."""
    from fleet_platform.workers.maintenance import (
        mark_stale_nodes,
    )

    session = _make_session([_rowcount_result(0), _rowcount_result(0)])

    with (
        patch("fleet_platform.workers.maintenance.get_sync_db", return_value=session),
        patch("fleet_platform.workers.maintenance.get_setting_sync", return_value="not-a-number"),
        patch("fleet_platform.workers.maintenance.sync_redis") as mock_redis,
    ):
        mock_redis.Redis.from_url.return_value = MagicMock()
        result = mark_stale_nodes()

    assert result["stale"] == 0
    assert result["offline"] == 0


def test_mark_stale_nodes_redis_failure_does_not_propagate():
    """A Redis error in the heartbeat path must be swallowed — task must succeed."""
    from fleet_platform.workers.maintenance import mark_stale_nodes

    session = _make_session([_rowcount_result(1), _rowcount_result(0)])

    with (
        patch("fleet_platform.workers.maintenance.get_sync_db", return_value=session),
        patch("fleet_platform.workers.maintenance.get_setting_sync", return_value=None),
        patch("fleet_platform.workers.maintenance.sync_redis") as mock_redis,
    ):
        mock_redis.Redis.from_url.side_effect = RuntimeError("redis down")
        result = mark_stale_nodes()

    assert "stale" in result
    assert "offline" in result


# ---------------------------------------------------------------------------
# cleanup_old_bootstrap_runs
# ---------------------------------------------------------------------------


def test_cleanup_old_bootstrap_runs_returns_deleted_and_cutoff():
    from fleet_platform.workers.maintenance import cleanup_old_bootstrap_runs

    setting_row = MagicMock()
    setting_row.value = "14"

    class _Session:
        _call = 0

        def execute(self, stmt):
            self._call += 1
            if self._call == 1:
                r = MagicMock()
                r.scalar_one_or_none.return_value = setting_row
                return r
            return _rowcount_result(7)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()):
        result = cleanup_old_bootstrap_runs()

    assert result["deleted"] == 7
    assert result["cutoff_days"] == 14


def test_cleanup_old_bootstrap_runs_defaults_to_30_days_when_no_setting():
    from fleet_platform.workers.maintenance import cleanup_old_bootstrap_runs

    class _Session:
        _call = 0

        def execute(self, stmt):
            self._call += 1
            if self._call == 1:
                r = MagicMock()
                r.scalar_one_or_none.return_value = None
                return r
            return _rowcount_result(0)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()):
        result = cleanup_old_bootstrap_runs()

    assert result["cutoff_days"] == 30


# ---------------------------------------------------------------------------
# reap_orphaned_bootstraps
# ---------------------------------------------------------------------------


def test_reap_orphaned_bootstraps_marks_both_run_and_node():
    """When stuck runs exist, both BootstrapRun and Node rows must be updated."""
    from fleet_platform.workers.maintenance import reap_orphaned_bootstraps

    stuck_id = uuid.uuid4()
    stmts = []

    class _Session:
        _call = 0

        def execute(self, stmt):
            stmts.append(stmt)
            self._call += 1
            if self._call == 1:
                return _select_scalars_result([stuck_id])
            return _rowcount_result(1)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()):
        result = reap_orphaned_bootstraps()

    assert result == {"reaped": 1}
    # SELECT + UPDATE BootstrapRun + UPDATE Node
    assert len(stmts) == 3, f"Expected 3 SQL statements, got {len(stmts)}"


def test_reap_orphaned_bootstraps_skips_node_update_when_no_stuck_runs():
    """When no stuck runs exist, the Node UPDATE must NOT be issued."""
    from fleet_platform.workers.maintenance import reap_orphaned_bootstraps

    stmts = []

    class _Session:
        _call = 0

        def execute(self, stmt):
            stmts.append(stmt)
            self._call += 1
            if self._call == 1:
                return _select_scalars_result([])
            return _rowcount_result(0)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()):
        result = reap_orphaned_bootstraps()

    assert result == {"reaped": 0}
    # SELECT + UPDATE BootstrapRun only (no Node UPDATE because list is empty)
    assert len(stmts) == 2, f"Expected 2 SQL statements, got {len(stmts)}"


# ---------------------------------------------------------------------------
# reap_stuck_pending_actions
# ---------------------------------------------------------------------------


def test_reap_stuck_pending_actions_returns_both_counts():
    from fleet_platform.workers.maintenance import reap_stuck_pending_actions

    session = _make_session([_rowcount_result(3), _rowcount_result(5)])

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=session):
        result = reap_stuck_pending_actions()

    assert result["reaped_executing"] == 3
    assert result["expired_pending"] == 5


def test_reap_stuck_pending_actions_zero_when_nothing_stuck():
    from fleet_platform.workers.maintenance import reap_stuck_pending_actions

    session = _make_session([_rowcount_result(0), _rowcount_result(0)])

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=session):
        result = reap_stuck_pending_actions()

    assert result == {"reaped_executing": 0, "expired_pending": 0}


# ---------------------------------------------------------------------------
# poll_salt_masters — backoff branch
# ---------------------------------------------------------------------------


def test_poll_salt_masters_skips_recently_checked_unreachable_master():
    """A master that is unreachable and was checked < backoff seconds ago must be skipped."""
    from datetime import UTC, datetime, timedelta

    from fleet_platform.workers.maintenance import (
        _SALT_UNREACHABLE_BACKOFF_SECONDS,
        poll_salt_masters,
    )

    recently_checked = datetime.now(UTC) - timedelta(seconds=_SALT_UNREACHABLE_BACKOFF_SECONDS // 2)
    master = MagicMock()
    master.status = "unreachable"
    master.last_checked_at = recently_checked
    master.enabled = True

    class _Session:
        def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [master]
            return r

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with (
        patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()),
        patch("fleet_platform.workers.maintenance.asyncio") as mock_asyncio,
        patch("fleet_platform.workers.maintenance.sync_redis") as mock_redis,
    ):
        mock_redis.Redis.from_url.return_value = MagicMock()
        result = poll_salt_masters()

    assert result["skipped"] == 1
    assert result["polled"] == 0
    # asyncio.run must NOT be called — no masters to probe
    mock_asyncio.run.assert_not_called()


def test_poll_salt_masters_probes_never_checked_unreachable_master():
    """A master with last_checked_at=None must always be probed regardless of status."""
    from fleet_platform.workers.maintenance import poll_salt_masters

    master = MagicMock()
    master.status = "unreachable"
    master.last_checked_at = None
    master.enabled = True

    probe_result = {"status": "reachable", "checks": []}

    class _Session:
        def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [master]
            return r

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _mock_run(coro):
        coro.close()  # close the coroutine to prevent "never awaited" warning
        return [probe_result]

    with (
        patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()),
        patch("fleet_platform.workers.maintenance.asyncio") as mock_asyncio,
        patch("fleet_platform.workers.maintenance.sync_redis") as mock_redis,
    ):
        mock_asyncio.run.side_effect = _mock_run
        mock_redis.Redis.from_url.return_value = MagicMock()
        result = poll_salt_masters()

    assert result["skipped"] == 0
    assert result["polled"] == 1
    mock_asyncio.run.assert_called_once()


def test_poll_salt_masters_exception_in_probe_does_not_abort_batch():
    """An Exception result from one probe must not prevent others from being committed."""
    from fleet_platform.workers.maintenance import poll_salt_masters

    master_ok = MagicMock()
    master_ok.status = "reachable"
    master_ok.last_checked_at = None
    master_ok.enabled = True

    master_bad = MagicMock()
    master_bad.status = "reachable"
    master_bad.last_checked_at = None
    master_bad.enabled = True

    class _Session:
        def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [master_ok, master_bad]
            return r

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    good_result = {"status": "reachable", "checks": []}
    bad_result = RuntimeError("probe failed")

    def _mock_run(coro):
        coro.close()  # close the coroutine to prevent "never awaited" warning
        return [bad_result, good_result]

    with (
        patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()),
        patch("fleet_platform.workers.maintenance.asyncio") as mock_asyncio,
        patch("fleet_platform.workers.maintenance.sync_redis") as mock_redis,
    ):
        mock_asyncio.run.side_effect = _mock_run
        mock_redis.Redis.from_url.return_value = MagicMock()
        result = poll_salt_masters()

    # One probe succeeded, one raised — polled should be 1
    assert result["polled"] == 1
    assert result["skipped"] == 0


# ---------------------------------------------------------------------------
# sweep_agent_quarantine
# ---------------------------------------------------------------------------


def test_sweep_agent_quarantine_returns_removed_count(tmp_path, monkeypatch):
    """sweep_agent_quarantine must delegate to agent_quarantine.sweep_expired and report count."""
    import fleet_platform.services.agent_quarantine as aq
    from fleet_platform.workers.maintenance import sweep_agent_quarantine

    monkeypatch.setattr(aq, "sweep_expired", lambda: ["/a", "/b", "/c"])

    result = sweep_agent_quarantine()
    assert result == {"removed": 3}


def test_sweep_agent_quarantine_returns_zero_when_nothing_expired(monkeypatch):
    import fleet_platform.services.agent_quarantine as aq
    from fleet_platform.workers.maintenance import sweep_agent_quarantine

    monkeypatch.setattr(aq, "sweep_expired", lambda: [])

    result = sweep_agent_quarantine()
    assert result == {"removed": 0}


# ---------------------------------------------------------------------------
# reap_orphaned_master_provisions
# ---------------------------------------------------------------------------


def test_reap_orphaned_master_provisions_updates_both_run_and_master():
    from fleet_platform.workers.maintenance import reap_orphaned_master_provisions

    stuck_master_id = uuid.uuid4()
    stmts = []

    class _Session:
        _call = 0

        def execute(self, stmt):
            stmts.append(stmt)
            self._call += 1
            if self._call == 1:
                return _select_scalars_result([stuck_master_id])
            return _rowcount_result(1)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=_Session()):
        result = reap_orphaned_master_provisions()

    assert result == {"reaped": 1}
    assert len(stmts) == 3, f"Expected SELECT + 2x UPDATE, got {len(stmts)}"
