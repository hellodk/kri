"""Chaos: planner failover and cloud-cap gating in the tier router (#715)."""

from __future__ import annotations

import uuid

import pytest

from fleet_platform.services import cost_tracker, tier_router


class FakeEndpoint:
    def __init__(self, name, caps, *, is_default=False):
        self.id = uuid.uuid4()
        self.name = name
        self.model_capabilities = caps
        self.enabled = True
        self.is_default = is_default
        self.model = "m"


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        class _S:
            def __init__(self, r):
                self._r = r

            def all(self):
                return self._r

        return _S(self._rows)


class FakeDB:
    def __init__(self, endpoints):
        self._e = endpoints

    async def execute(self, _q):
        return _Result(self._e)


@pytest.fixture(autouse=True)
def _reset():
    tier_router.STATE.reset()
    cost_tracker.STATE.reset()
    yield
    tier_router.STATE.reset()
    cost_tracker.STATE.reset()


async def test_failover_when_one_planner_dies():
    p1 = FakeEndpoint("planner-mm1", "planner")
    p2 = FakeEndpoint("planner-mm2", "planner")
    db = FakeDB([p1, p2])
    # mm1 falls over mid-flight.
    tier_router.STATE.mark_unhealthy(str(p1.id))
    res = await tier_router.select_endpoint(db, "planner")
    assert res.endpoint is p2


async def test_all_planners_down_degrades_to_cloud_for_admin():
    p1 = FakeEndpoint("planner-mm1", "planner")
    cloud = FakeEndpoint("claude", "cloud")
    db = FakeDB([p1, cloud])
    tier_router.STATE.mark_unhealthy(str(p1.id))
    res = await tier_router.select_endpoint(db, "planner", allow_cloud=True)
    assert res.via_cloud is True


async def test_cloud_blocked_when_daily_cap_exhausted():
    p1 = FakeEndpoint("planner-mm1", "planner")
    cloud = FakeEndpoint("claude", "cloud")
    db = FakeDB([p1, cloud])
    tier_router.STATE.mark_unhealthy(str(p1.id))
    # Blow the cap so even admin cloud fallback is refused (circuit breaker).
    huge = int(cost_tracker.DAILY_CAP_USD / cost_tracker.COST_PER_1K_TOKENS_USD * 1000) + 5000
    cost_tracker.record_tokens(huge, 0)
    res = await tier_router.select_endpoint(db, "planner", allow_cloud=True)
    assert res is None


async def test_recovered_planner_is_reused_after_cooldown(monkeypatch):
    p1 = FakeEndpoint("planner-mm1", "planner")
    db = FakeDB([p1])
    tier_router.STATE.mark_unhealthy(str(p1.id), cooldown_s=10)
    assert await tier_router.select_endpoint(db, "planner") is None
    base = tier_router.time.monotonic()
    monkeypatch.setattr(tier_router.time, "monotonic", lambda: base + 11)
    res = await tier_router.select_endpoint(db, "planner")
    assert res.endpoint is p1
