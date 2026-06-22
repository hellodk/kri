"""Unit tests for the capability-tag tier router (#712).

No DB/network: a fake async session returns hand-built endpoints so we can
assert chain fallback, health cooldown, least-loaded selection, and the
admin-gated cloud fallback in isolation.
"""

from __future__ import annotations

import uuid

import pytest

from fleet_platform.services import tier_router
from fleet_platform.services.tier_router import RouteResult


class FakeEndpoint:
    def __init__(self, name, caps, *, enabled=True, is_default=False, model="m"):
        self.id = uuid.uuid4()
        self.name = name
        self.model_capabilities = caps
        self.enabled = enabled
        self.is_default = is_default
        self.model = model


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class FakeDB:
    """Returns only the enabled endpoints (mirrors the WHERE enabled clause)."""

    def __init__(self, endpoints):
        self._endpoints = endpoints

    async def execute(self, _query):
        return _Result([e for e in self._endpoints if e.enabled])


@pytest.fixture(autouse=True)
def _reset_state():
    tier_router.STATE.reset()
    yield
    tier_router.STATE.reset()


async def test_routes_to_specific_tag_first():
    planner = FakeEndpoint("planner-mm1", "planner")
    general = FakeEndpoint("general-x", "general")
    db = FakeDB([planner, general])
    res = await tier_router.select_endpoint(db, "planner")
    assert isinstance(res, RouteResult)
    assert res.endpoint is planner
    assert res.matched_tag == "planner"
    assert res.via_cloud is False


async def test_falls_back_down_chain_to_general():
    general = FakeEndpoint("general-x", "general")
    db = FakeDB([general])
    res = await tier_router.select_endpoint(db, "coder_yaml")
    assert res.endpoint is general
    assert res.matched_tag == "general"


async def test_no_local_match_without_cloud_returns_none():
    cloud = FakeEndpoint("claude", "cloud")
    db = FakeDB([cloud])
    assert await tier_router.select_endpoint(db, "planner", allow_cloud=False) is None


async def test_cloud_fallback_only_when_allowed():
    cloud = FakeEndpoint("claude", "cloud")
    db = FakeDB([cloud])
    res = await tier_router.select_endpoint(db, "planner", allow_cloud=True)
    assert res.endpoint is cloud
    assert res.via_cloud is True
    assert res.matched_tag == "cloud"


async def test_unhealthy_endpoint_is_skipped():
    a = FakeEndpoint("planner-a", "planner")
    b = FakeEndpoint("planner-b", "planner")
    db = FakeDB([a, b])
    tier_router.STATE.mark_unhealthy(str(a.id))
    res = await tier_router.select_endpoint(db, "planner")
    assert res.endpoint is b


async def test_least_loaded_wins():
    a = FakeEndpoint("planner-a", "planner")
    b = FakeEndpoint("planner-b", "planner")
    db = FakeDB([a, b])
    tier_router.STATE.acquire(str(a.id))
    tier_router.STATE.acquire(str(a.id))
    tier_router.STATE.acquire(str(b.id))
    res = await tier_router.select_endpoint(db, "planner")
    assert res.endpoint is b  # load 1 < load 2


async def test_lease_increments_then_releases():
    a = FakeEndpoint("planner-a", "planner")
    assert tier_router.STATE.load(str(a.id)) == 0
    with tier_router.lease(a):
        assert tier_router.STATE.load(str(a.id)) == 1
    assert tier_router.STATE.load(str(a.id)) == 0


async def test_health_cooldown_expires(monkeypatch):
    a = FakeEndpoint("planner-a", "planner")
    eid = str(a.id)
    tier_router.STATE.mark_unhealthy(eid, cooldown_s=10)
    assert tier_router.STATE.is_healthy(eid) is False
    # Jump past the cooldown window.
    base = tier_router.time.monotonic()
    monkeypatch.setattr(tier_router.time, "monotonic", lambda: base + 11)
    assert tier_router.STATE.is_healthy(eid) is True


async def test_tier_status_groups_by_capability():
    planner = FakeEndpoint("planner-mm1", "planner")
    coder = FakeEndpoint("coder-mm3", "coder_yaml")
    db = FakeDB([planner, coder])
    status = await tier_router.tier_status(db)
    assert any(e["name"] == "planner-mm1" for e in status["planner"])
    assert any(e["name"] == "coder-mm3" for e in status["coder_yaml"])
    assert status["embed"] == []


def test_parse_tags_handles_messy_input():
    e = FakeEndpoint("x", " Planner , CODER_yaml ,, ")
    assert tier_router.parse_tags(e) == {"planner", "coder_yaml"}
