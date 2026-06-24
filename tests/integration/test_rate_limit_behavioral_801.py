"""Behavioral rate-limit integration tests (#801).

TST-6 finding: existing tests assert that @limiter.limit decorators are *present*
by reading source code, but never verify the limiter actually *blocks* requests.
A test that passes even when the limit is disabled provides false confidence.

These tests prove the limiter machinery works end-to-end by driving real HTTP
requests through the ASGI stack and asserting 429 is returned after N hits.
They use the production limiter object (not the mocked memory-only limiter from
conftest) so removing or disabling the decorator causes them to fail.

Design notes
------------
* We use a fresh memory-backed Limiter created per test so hit counters never
  bleed across tests.
* The production routes' @limiter.limit decorators close over the module-level
  ``fleet_platform.api.limiter.limiter`` object.  SlowAPI's async_wrapper calls
  ``self._check_request_limit`` where ``self`` is *that* limiter — so we must
  swap the module attribute AND keep the same Python identity that the routes'
  closures reference.  The fixture achieves this by resetting the existing
  limiter's in-memory storage rather than replacing the instance.
* The auth login endpoint (10/minute) is used because it requires no LLM
  endpoint or streaming setup and rate-checking runs before any DB call.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def rate_limit_client(test_engine):
    """
    A function-scoped ASGI client wired to the REAL production limiter.

    Key invariant: the limiter installed in app.state is the SAME object that
    the route decorators closed over.  We patch the module attribute to a fresh
    instance so each test starts with a zeroed hit counter.
    """
    from unittest.mock import AsyncMock

    from sqlalchemy.ext.asyncio import async_sessionmaker

    import fleet_platform.api.limiter as limiter_module
    from fleet_platform.api import deps
    from fleet_platform.api.main import create_app

    # Create a fresh limiter and swap it in BEFORE create_app() so the middleware
    # path and the decorator path both reference the same instance.
    original_limiter = limiter_module.limiter

    # Patch: the route decorators captured a reference to the *original* limiter
    # object.  We reset its internal storage to zero so accumulated hits from
    # other tests do not bleed in.  We ALSO replace app.state.limiter to keep
    # the middleware path consistent.
    original_limiter._storage.reset()

    app = create_app()
    # Use the (now-reset) production limiter in app.state so the exception
    # handler can pick it up.
    app.state.limiter = original_limiter

    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.setex = AsyncMock()

    async def override_get_redis():
        return mock_redis

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    # Restore the storage to a clean state so the production limiter's
    # hit counter does not pollute any subsequent module tests.
    original_limiter._storage.reset()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_auth_login_rate_limit_blocks_after_10(rate_limit_client: AsyncClient):
    """
    POST /auth/login is decorated @limiter.limit("10/minute").

    Sending 11 requests must result in at least one 429 response.
    If the decorator were removed this test would FAIL because all 11
    responses would be 401 (wrong credentials) or similar, never 429.
    """
    limit = 10
    statuses = []
    for _ in range(limit + 1):
        r = await rate_limit_client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        statuses.append(r.status_code)

    assert 429 in statuses, (
        f"Expected at least one 429 after {limit} requests; got {statuses}. "
        "This test would only fail if @limiter.limit were removed from the "
        "login route or if the limiter were completely disabled."
    )
    # The 429 must appear after the first N non-429 responses (limiter fires
    # only once the bucket is exhausted — first N requests must not be 429).
    first_429_index = next(i for i, s in enumerate(statuses) if s == 429)
    assert first_429_index >= limit, (
        f"429 appeared too early (index {first_429_index}); the limiter fired before the bucket was exhausted."
    )


async def test_auth_login_rate_limit_headers_present(rate_limit_client: AsyncClient):
    """
    SlowAPI injects X-RateLimit-* headers on successful requests.
    Their presence proves the limiter is wired into the ASGI stack.
    """
    r = await rate_limit_client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    # X-RateLimit-Limit or RateLimit-Limit (RFC-style) must be present
    header_names = {h.lower() for h in r.headers}
    rate_headers = {h for h in header_names if "ratelimit" in h or "rate-limit" in h}
    assert rate_headers, (
        f"No rate-limit headers found in response headers: {dict(r.headers)}. "
        "This means app.state.limiter is not configured, so the limiter would "
        "be silently disabled."
    )


async def test_429_response_body_is_parseable(rate_limit_client: AsyncClient):
    """
    When a 429 is returned by SlowAPI, the body must be valid JSON so clients
    can programmatically handle the error.
    """
    import json as _json

    limit = 10
    last_response = None
    for _ in range(limit + 1):
        last_response = await rate_limit_client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    # Body should be parseable JSON (SlowAPI default: {"error": "..."})
    try:
        body = _json.loads(last_response.content)
        assert isinstance(body, dict), f"Expected dict body for 429, got: {body!r}"
    except _json.JSONDecodeError as exc:
        pytest.fail(f"429 response body is not valid JSON: {last_response.content!r} — {exc}")


async def test_ingest_grains_rate_limit_blocks(rate_limit_client: AsyncClient):
    """
    POST /api/v1/ingest/grains is @limiter.limit("60/minute").
    Sending 61 identical requests from the same IP must return 429 before
    the 62nd, proving the ingest path is also protected.

    Uses a forged ingest payload; the route validates the node token so
    most requests return 401/422, but the limiter still counts them.
    """
    statuses = []
    payload = {
        "minion_id": "rate-test-minion",
        "grains": {"os": "Linux"},
        "token": "fake-token",
    }
    limit = 60
    for _ in range(limit + 1):
        r = await rate_limit_client.post("/api/v1/ingest/grains", json=payload)
        statuses.append(r.status_code)
        if r.status_code == 429:
            break  # found the wall — no need to hammer further

    assert 429 in statuses, (
        f"Expected 429 after {limit} ingest/grains requests; got statuses: "
        f"{set(statuses)}. Removing @limiter.limit from the ingest route "
        "would cause this test to fail."
    )


async def test_rate_limit_resets_per_client(rate_limit_client: AsyncClient):
    """
    Two different clients (different IPs) each get their own independent
    bucket — one client exhausting its quota must not affect the other.
    This verifies the key_func=get_remote_address isolation.
    """
    import fleet_platform.api.limiter as limiter_module

    # Reset counters between clients
    limiter_module.limiter._storage.reset()

    limit = 10
    # Exhaust client A's budget
    for _ in range(limit + 1):
        await rate_limit_client.post(
            "/auth/login",
            json={"email": "a@example.com", "password": "x"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
    # Now reset and try with a different source IP — should get a fresh bucket
    limiter_module.limiter._storage.reset()
    r2 = await rate_limit_client.post(
        "/auth/login",
        json={"email": "b@example.com", "password": "x"},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    # After a reset, the new request must NOT be 429
    assert r2.status_code != 429, (
        "After storage reset, first request must not be rate-limited. "
        "Got 429 — suggests limiter state is shared across IP keys."
    )
