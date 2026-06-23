"""TDD tests for #734 — poll_salt_masters must probe all masters concurrently.

Failing tests confirm the bug (serial asyncio.run per master).
After the fix they must all pass with:
  - a single asyncio.run() call regardless of master count
  - peak concurrency == number of masters to probe
  - per-probe exceptions handled without aborting the batch
  - backoff skip logic preserved
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_master(mid, status="reachable", last_checked_at=None):
    m = MagicMock()
    m.id = mid
    m.status = status
    m.last_checked_at = last_checked_at
    m.enabled = True
    return m


def _probe_result(status="reachable"):
    return {"status": status, "checks": []}


class _FakeDB:
    """Minimal synchronous DB context-manager stand-in."""

    def __init__(self, masters):
        self._masters = masters
        self.committed = False

    def execute(self, stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._masters
        return result

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _patch_redis(monkeypatch):
    monkeypatch.setattr(
        "fleet_platform.workers.maintenance.sync_redis.Redis.from_url",
        lambda *a, **kw: MagicMock(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_poll_salt_masters_single_event_loop(monkeypatch):
    """All probes must be issued in one asyncio.run() call, not one per master.

    FAILS before fix: the serial loop calls asyncio.run() once per master.
    PASSES after fix: a single asyncio.run(_probe_all(...)) call.
    """
    masters = [_make_master(i) for i in range(3)]
    db = _FakeDB(masters)

    asyncio_run_calls: list[int] = []
    real_run = asyncio.run

    def counting_run(coro, **kwargs):
        asyncio_run_calls.append(1)
        return real_run(coro, **kwargs)

    monkeypatch.setattr("fleet_platform.workers.maintenance.asyncio.run", counting_run)
    monkeypatch.setattr("fleet_platform.workers.maintenance.get_sync_db", lambda: db)
    _patch_redis(monkeypatch)

    async def fake_probe(master):
        return _probe_result()

    monkeypatch.setattr("fleet_platform.workers.maintenance.run_probe", fake_probe)

    from fleet_platform.workers.maintenance import poll_salt_masters

    result = poll_salt_masters()

    assert len(asyncio_run_calls) == 1, (
        f"Expected exactly 1 asyncio.run() call for {len(masters)} masters; "
        f"got {len(asyncio_run_calls)} — probes are running serially"
    )
    assert result["polled"] == 3
    assert result["skipped"] == 0


def test_poll_salt_masters_probes_overlap(monkeypatch):
    """run_probe coroutines must overlap: peak concurrency equals master count.

    FAILS before fix: each asyncio.run() completes before the next starts,
    so peak concurrency is always 1.
    PASSES after fix: asyncio.gather runs them all at once.
    """
    masters = [_make_master(i) for i in range(3)]
    db = _FakeDB(masters)

    peak: dict[str, int] = {"val": 0}
    active: dict[str, int] = {"val": 0}

    async def fake_probe(master):
        active["val"] += 1
        peak["val"] = max(peak["val"], active["val"])
        await asyncio.sleep(0)  # yield — all peer coroutines should start
        active["val"] -= 1
        return _probe_result()

    monkeypatch.setattr("fleet_platform.workers.maintenance.get_sync_db", lambda: db)
    monkeypatch.setattr("fleet_platform.workers.maintenance.run_probe", fake_probe)
    _patch_redis(monkeypatch)

    from fleet_platform.workers.maintenance import poll_salt_masters

    result = poll_salt_masters()

    assert peak["val"] == 3, (
        f"Expected peak concurrency of 3; got {peak['val']} — probes are running serially, not concurrently"
    )
    assert result["polled"] == 3


def test_poll_salt_masters_exception_does_not_abort_batch(monkeypatch):
    """A single failing probe must not prevent the rest from completing.

    FAILS before fix: an exception from asyncio.run() would propagate up
    and abort the entire loop (polled count < expected).
    PASSES after fix: return_exceptions=True in gather catches per-probe errors.
    """
    masters = [_make_master(0), _make_master(1), _make_master(2)]
    db = _FakeDB(masters)

    probed_ids: list[int] = []

    async def fake_probe(master):
        probed_ids.append(master.id)
        if master.id == 1:
            raise RuntimeError("salt-api unreachable")
        return _probe_result("reachable")

    monkeypatch.setattr("fleet_platform.workers.maintenance.get_sync_db", lambda: db)
    monkeypatch.setattr("fleet_platform.workers.maintenance.run_probe", fake_probe)
    _patch_redis(monkeypatch)

    from fleet_platform.workers.maintenance import poll_salt_masters

    result = poll_salt_masters()

    assert sorted(probed_ids) == [0, 1, 2], "all 3 probes must have been issued"
    assert result["polled"] == 2, "2 successful probes must be counted"
    assert result["skipped"] == 0


def test_poll_salt_masters_commit_after_io(monkeypatch):
    """DB commit must happen AFTER all probes complete, not interleaved with IO.

    FAILS before fix: commit() is called inside the loop while probes are
    running (no strict separation of IO and DB write phases).
    PASSES after fix: DB session is released/committed only after gather returns.
    """
    masters = [_make_master(i) for i in range(2)]
    db = _FakeDB(masters)

    events: list[str] = []
    original_commit = db.commit

    def tracked_commit():
        events.append("commit")
        original_commit()

    db.commit = tracked_commit

    async def fake_probe(master):
        events.append(f"probe:{master.id}")
        await asyncio.sleep(0)
        return _probe_result()

    monkeypatch.setattr("fleet_platform.workers.maintenance.get_sync_db", lambda: db)
    monkeypatch.setattr("fleet_platform.workers.maintenance.run_probe", fake_probe)
    _patch_redis(monkeypatch)

    from fleet_platform.workers.maintenance import poll_salt_masters

    poll_salt_masters()

    assert events[-1] == "commit", "commit must be the last event"
    probe_events = [e for e in events if e.startswith("probe:")]
    assert len(probe_events) == 2, "both probes must have fired"
    commit_idx = events.index("commit")
    for pe in probe_events:
        assert events.index(pe) < commit_idx, f"probe event '{pe}' must occur before commit"


def test_poll_salt_masters_skips_backoff_masters(monkeypatch):
    """Masters in backoff window must still be skipped.

    Preserved behaviour — must pass both before and after fix.
    """
    now = datetime.now(UTC)
    recent = now - timedelta(seconds=10)  # within backoff window

    masters = [
        _make_master(0, status="unreachable", last_checked_at=recent),
        _make_master(1, status="reachable"),
    ]
    db = _FakeDB(masters)

    probed_ids: list[int] = []

    async def fake_probe(master):
        probed_ids.append(master.id)
        return _probe_result("reachable")

    monkeypatch.setattr("fleet_platform.workers.maintenance.get_sync_db", lambda: db)
    monkeypatch.setattr("fleet_platform.workers.maintenance.run_probe", fake_probe)
    _patch_redis(monkeypatch)

    from fleet_platform.workers.maintenance import poll_salt_masters

    result = poll_salt_masters()

    assert result["skipped"] == 1
    assert result["polled"] == 1
    assert 0 not in probed_ids, "backoff master (id=0) must not be probed"
    assert 1 in probed_ids, "non-backoff master (id=1) must be probed"
