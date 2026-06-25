"""Behavioral rate-limit tests for node action endpoints (issue #616).

Previously these tests asserted that ``@limiter.limit(...)`` and
``request: Request`` were *present in the source* by reading ``node_actions.py``
and grepping for substrings. A string match gives false confidence: it still
passes if the limiter is disabled, if the route is never mounted, or if the
decorator is attached to the wrong function — and it breaks on harmless
refactors (whitespace, quote style).

These tests instead assert the *runtime* contract:

* the SlowAPI limiter has actually registered the expected limit (amount +
  window) for each endpoint function — proving the decorator ran at import and
  produced a real ``Limit`` object;
* each endpoint is mounted on its router with the right path/method;
* each handler accepts the ``request`` parameter SlowAPI needs to key the
  limiter; and
* the limiter genuinely returns HTTP 429 once the bucket is exhausted, driven
  through the real ASGI stack.
"""

from __future__ import annotations

import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from fleet_platform.api import deps
from fleet_platform.api.limiter import limiter
from fleet_platform.api.main import create_app
from fleet_platform.api.routes import node_actions


def _limit_windows(endpoint) -> set[tuple[int, int]]:
    """Return the set of (amount, window_seconds) limits SlowAPI registered for an endpoint.

    SlowAPI stores limits keyed by ``f"{module}.{name}"`` when the
    ``@limiter.limit`` decorator executes at import time. An empty set means the
    decorator never ran for that function (e.g. it was removed).
    """
    key = f"{endpoint.__module__}.{endpoint.__name__}"
    limits = limiter._route_limits.get(key, [])
    return {(lim.limit.amount, lim.limit.GRANULARITY.seconds) for lim in limits}


def test_rate_limiter_importable():
    """The shared limiter must be importable (routes close over this object)."""
    assert limiter is not None


def test_request_node_action_limited_5_per_minute():
    """request_node_action is rate-limited at 5/minute at runtime, not just in source."""
    assert (5, 60) in _limit_windows(node_actions.request_node_action), (
        "request_node_action must register a 5/minute SlowAPI limit"
    )


def test_approve_and_reject_limited_20_per_minute():
    """approve_action and reject_action are each rate-limited at 20/minute at runtime."""
    assert (20, 60) in _limit_windows(node_actions.approve_action), "approve_action must register a 20/minute limit"
    assert (20, 60) in _limit_windows(node_actions.reject_action), "reject_action must register a 20/minute limit"


def test_all_three_handlers_accept_request_param():
    """SlowAPI requires a ``request`` parameter on every rate-limited handler.

    Asserted via the live function signature rather than a source regex, so the
    test reflects what FastAPI/SlowAPI actually introspect at runtime.
    """
    for fn in (node_actions.request_node_action, node_actions.approve_action, node_actions.reject_action):
        assert "request" in inspect.signature(fn).parameters, (
            f"{fn.__name__} must accept a `request` parameter for SlowAPI rate limiting"
        )


def test_endpoints_are_mounted_on_routers():
    """The three rate-limited endpoints are actually mounted (POST) on their routers."""

    def _post_paths(router):
        return {r.path for r in router.routes if getattr(r, "methods", None) and "POST" in r.methods}

    request_paths = _post_paths(node_actions.router)
    action_paths = _post_paths(node_actions.actions_router)
    assert any(p.endswith("/actions") for p in request_paths), f"request_node_action route missing: {request_paths}"
    assert any(p.endswith("/approve") for p in action_paths), f"approve route missing: {action_paths}"
    assert any(p.endswith("/reject") for p in action_paths), f"reject route missing: {action_paths}"


# ---------------------------------------------------------------------------
# End-to-end enforcement: the approve endpoint has no auth dependency, so we
# can drive the limiter directly through the ASGI stack and prove it returns
# 429 once the bucket is exhausted. This fails if the decorator is removed or
# the limiter is disabled — the exact regressions the old source-scrape missed.
# ---------------------------------------------------------------------------


class _FakeResult:
    def scalar_one_or_none(self):
        return None  # token not found -> handler returns a clean 404 (before the 429 wall)


class _FakeSession:
    async def execute(self, *args, **kwargs):
        return _FakeResult()

    async def rollback(self):
        pass


@pytest.fixture
def approve_app():
    # Reset the shared limiter's in-memory counters so hits accumulated by other
    # tests/modules don't bleed in and trip 429 prematurely.
    limiter._storage.reset()
    app = create_app()
    app.state.limiter = limiter

    async def _override_db():
        yield _FakeSession()

    app.dependency_overrides[deps.get_db] = _override_db
    yield app
    limiter._storage.reset()


async def test_approve_endpoint_returns_429_after_20_requests(approve_app):
    """The 21st POST to /api/v1/actions/{token}/approve within the window is rejected with 429."""
    transport = ASGITransport(app=approve_app)
    statuses: list[int] = []
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(22):
            resp = await client.post("/api/v1/actions/sometoken/approve")
            statuses.append(resp.status_code)

    assert 429 in statuses, f"limiter never fired on approve route: {statuses}"
    first_429 = statuses.index(429)
    assert first_429 >= 20, f"429 fired before the 20/minute bucket was exhausted (index {first_429}): {statuses}"
    # The pre-limit responses are the handler's real 404 (token not found), which
    # proves the limiter sits in front of a live, reachable route — not a stub.
    assert statuses[0] == 404, f"expected 404 from approve handler before the limit, got {statuses[0]}"
