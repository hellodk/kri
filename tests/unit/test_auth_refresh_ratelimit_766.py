"""Behavioral tests for #766 — rate-limit the auth/refresh endpoint.

Previously these tests read ``auth.py`` and regex-matched the source for a
``@limiter.limit(...)`` decorator above ``async def refresh`` and a ``request``
parameter. Source matches are brittle (whitespace/quote changes break them) and
give false confidence (they pass even if the limiter is disabled or unmounted).

These tests assert the runtime contract instead:

1. the SlowAPI limiter registered a 10/minute limit for ``refresh`` (matching
   ``login``), proving the decorator ran;
2. ``refresh`` accepts the ``request`` parameter SlowAPI requires (live
   signature);
3. ``POST /auth/refresh`` is mounted on the router; and
4. the limiter genuinely returns 429 once the bucket is exhausted, driven
   through the real ASGI stack.
"""

from __future__ import annotations

import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from fleet_platform.api import deps
from fleet_platform.api.limiter import limiter
from fleet_platform.api.main import create_app
from fleet_platform.api.routes import auth


def _limit_windows(endpoint) -> set[tuple[int, int]]:
    key = f"{endpoint.__module__}.{endpoint.__name__}"
    return {(lim.limit.amount, lim.limit.GRANULARITY.seconds) for lim in limiter._route_limits.get(key, [])}


def test_refresh_rate_limited_ten_per_minute():
    """refresh registers a 10/minute SlowAPI limit at runtime (matches login)."""
    assert (10, 60) in _limit_windows(auth.refresh), "refresh must register a 10/minute limit"


def test_refresh_limit_matches_login():
    """The refresh limit must match the login limit, per #766."""
    assert _limit_windows(auth.refresh) == _limit_windows(auth.login), (
        "refresh and login must share the same rate limit"
    )


def test_refresh_handler_accepts_request():
    """SlowAPI requires the handler to accept a `request` parameter (live signature)."""
    assert "request" in inspect.signature(auth.refresh).parameters, (
        "refresh() must accept a `request` parameter for SlowAPI rate limiting"
    )


def test_refresh_route_accessible():
    """The /auth/refresh route must be importable and present in the router."""
    paths = [getattr(r, "path", "") for r in auth.router.routes]
    assert any(p.endswith("/refresh") for p in paths), f"POST /auth/refresh route not found; routes: {paths}"


# ---------------------------------------------------------------------------
# End-to-end enforcement of the 10/minute limit through the real ASGI stack.
# refresh validates the token before touching the DB/redis, so a bogus token
# yields a clean 401 until the limiter fires — proving the limit is live.
# ---------------------------------------------------------------------------


class _FakeSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("DB should not be reached with an invalid refresh token")

    async def rollback(self):
        pass


@pytest.fixture
def refresh_app():
    limiter._storage.reset()  # zero shared counters so other tests don't trip the limit early
    app = create_app()
    app.state.limiter = limiter

    async def _override_db():
        yield _FakeSession()

    async def _override_redis():
        from unittest.mock import AsyncMock

        r = AsyncMock()
        r.get.return_value = None
        return r

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_redis] = _override_redis
    yield app
    limiter._storage.reset()


async def test_refresh_returns_429_after_10_requests(refresh_app):
    """The 11th POST /auth/refresh within the window is rejected with 429."""
    transport = ASGITransport(app=refresh_app)
    statuses: list[int] = []
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(12):
            resp = await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
            statuses.append(resp.status_code)

    assert 429 in statuses, f"limiter never fired on /auth/refresh: {statuses}"
    first_429 = statuses.index(429)
    assert first_429 >= 10, f"429 fired before the 10/minute bucket was exhausted (index {first_429}): {statuses}"
    # Pre-limit responses are the handler's real 401 (invalid token), proving the
    # limiter guards a live route rather than a stub.
    assert statuses[0] == 401, f"expected 401 from refresh handler before the limit, got {statuses[0]}"
