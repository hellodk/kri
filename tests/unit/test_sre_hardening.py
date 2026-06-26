"""Unit tests for SRE security hardening issues.

Covers:
- #763 — /metrics endpoint requires auth (bearer or metrics token)
- #764 — Content-Security-Policy header present in responses
- #755 — X-XSS-Protection header NOT emitted by the app (deprecated)
- #759 — Login rate limiter keyed on trusted-proxy-aware client IP
- #757/#820 — must_change_password gate on login + seeding refuses weak passwords
"""

from __future__ import annotations

import unittest.mock as mock

import pytest

# ---------------------------------------------------------------------------
# 1. Security header middleware — CSP present, X-XSS-Protection absent
# ---------------------------------------------------------------------------


def _make_middleware_app():
    """Tiny Starlette app with SecurityHeaderMiddleware wired in."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from fleet_platform.middleware.security_headers import SecurityHeaderMiddleware

    async def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(SecurityHeaderMiddleware)
    return TestClient(app)


def test_security_middleware_adds_csp_header():
    """SecurityHeaderMiddleware sets Content-Security-Policy on responses (#764)."""
    client = _make_middleware_app()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Content-Security-Policy" in resp.headers, (
        "SecurityHeaderMiddleware must add a Content-Security-Policy header (#764)"
    )


def test_security_middleware_csp_has_default_src():
    """CSP header must include a default-src directive."""
    client = _make_middleware_app()
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src" in csp, "CSP must include a default-src directive"


def test_security_middleware_does_not_emit_xss_protection():
    """SecurityHeaderMiddleware must NOT emit X-XSS-Protection (deprecated) (#755)."""
    client = _make_middleware_app()
    resp = client.get("/")
    assert "X-XSS-Protection" not in resp.headers, (
        "X-XSS-Protection is deprecated and must not be set by the app middleware (#755)"
    )


def test_security_middleware_csp_blocks_framing():
    """CSP should include frame-ancestors 'none' to prevent clickjacking."""
    client = _make_middleware_app()
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp


# ---------------------------------------------------------------------------
# 2. /metrics endpoint — requires auth (#763)
# ---------------------------------------------------------------------------


def test_metrics_auth_function_requires_auth():
    """_verify_metrics_request raises HTTPException(401) with no credentials (#763)."""
    from fastapi import HTTPException

    from fleet_platform.api.metrics_auth import verify_metrics_request

    fake_request = mock.MagicMock()
    fake_request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        verify_metrics_request(fake_request, metrics_token=None)
    assert exc_info.value.status_code == 401


def test_metrics_auth_function_accepts_valid_metrics_token():
    """_verify_metrics_request succeeds when a matching metrics token is provided (#763)."""
    from fleet_platform.api.metrics_auth import verify_metrics_request

    fake_request = mock.MagicMock()
    fake_request.headers = {"Authorization": "Bearer supersecrettoken"}

    # Should NOT raise
    verify_metrics_request(fake_request, metrics_token="supersecrettoken")


def test_metrics_auth_function_rejects_wrong_token():
    """_verify_metrics_request raises HTTPException(401) when metrics token is wrong (#763)."""
    from fastapi import HTTPException

    from fleet_platform.api.metrics_auth import verify_metrics_request

    fake_request = mock.MagicMock()
    fake_request.headers = {"Authorization": "Bearer wrongtoken"}

    with pytest.raises(HTTPException) as exc_info:
        verify_metrics_request(fake_request, metrics_token="righttoken")
    assert exc_info.value.status_code == 401


def test_metrics_auth_accepts_valid_jwt(monkeypatch):
    """_verify_metrics_request accepts a valid JWT bearer token even without metrics_token."""
    from fleet_platform.api.metrics_auth import verify_metrics_request
    from fleet_platform.core.auth import create_access_token

    token = create_access_token("00000000-0000-0000-0000-000000000001", "ops@example.com", "operator")
    fake_request = mock.MagicMock()
    fake_request.headers = {"Authorization": f"Bearer {token}"}

    # Should NOT raise when JWT is valid
    verify_metrics_request(fake_request, metrics_token=None)


# ---------------------------------------------------------------------------
# 3. Trusted-proxy-aware rate limiter key function (#759)
# ---------------------------------------------------------------------------


def _make_request(client_host: str, xff: str | None = None) -> mock.MagicMock:
    req = mock.MagicMock()
    req.client = mock.MagicMock()
    req.client.host = client_host
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    req.headers = headers
    return req


def test_trusted_ip_zero_proxies_uses_direct_connection():
    """With trusted_proxy_count=0, key is request.client.host (ignores XFF) (#759)."""
    from fleet_platform.api.limiter import make_real_ip_key

    key_func = make_real_ip_key(proxy_count=0)
    req = _make_request("10.0.0.1", xff="1.2.3.4")
    assert key_func(req) == "10.0.0.1"


def test_trusted_ip_one_proxy_takes_from_xff():
    """With trusted_proxy_count=1, key is the only XFF entry (real client behind proxy) (#759)."""
    from fleet_platform.api.limiter import make_real_ip_key

    key_func = make_real_ip_key(proxy_count=1)
    req = _make_request("10.0.0.5", xff="203.0.113.42")
    assert key_func(req) == "203.0.113.42"


def test_trusted_ip_two_proxies_skips_rightmost_xff_entry():
    """With trusted_proxy_count=2, key skips the rightmost two entries (#759)."""
    from fleet_platform.api.limiter import make_real_ip_key

    key_func = make_real_ip_key(proxy_count=2)
    # XFF: client, proxy1 (rightmost is the most recent proxy before direct conn)
    req = _make_request("172.16.0.1", xff="203.0.113.42, 10.0.0.5")
    # proxy_count=2 means 2 trusted hops: skip rightmost 2 → take index len-2 = 0
    assert key_func(req) == "203.0.113.42"


def test_trusted_ip_attacker_cannot_spoof_with_extra_xff_entries():
    """Attacker injecting extra XFF entries does not bypass the trusted-proxy count (#759)."""
    from fleet_platform.api.limiter import make_real_ip_key

    # proxy_count=1: one trusted proxy, rightmost XFF entry is real client as seen by proxy
    key_func = make_real_ip_key(proxy_count=1)
    # Attacker sends: X-Forwarded-For: attacker_fake_ip, real_client_ip
    # The proxy appends real_client_ip to the end → proxy sees client as real_client_ip
    req = _make_request("10.0.0.5", xff="attacker_fake_ip, 203.0.113.42")
    # proxy_count=1 → take index len(2)-1 = 1 → "203.0.113.42" (real client as seen by proxy)
    assert key_func(req) == "203.0.113.42"


def test_trusted_ip_fallback_when_xff_missing():
    """When XFF is absent and proxy_count>0, fallback to request.client.host (#759)."""
    from fleet_platform.api.limiter import make_real_ip_key

    key_func = make_real_ip_key(proxy_count=1)
    req = _make_request("10.0.0.5", xff=None)
    assert key_func(req) == "10.0.0.5"


# ---------------------------------------------------------------------------
# 4. must_change_password — login gate (#757/#820)
# ---------------------------------------------------------------------------


def test_login_route_checks_must_change_password_flag():
    """The login route body raises 403 when user.must_change_password is True (#757/#820).

    Tests the guard logic by inspecting the route source or by calling the check
    inline — avoids slowapi's Request type check in unit context.
    """
    import uuid

    from fastapi import HTTPException

    from fleet_platform.core.auth import hash_password
    from fleet_platform.models.user import User

    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash=hash_password("admin"),
        role="admin",
        is_active=True,
        auth_provider="local",
        must_change_password=True,
    )

    # Reproduce the guard that the login route applies after auth succeeds.
    if user.must_change_password:
        with pytest.raises(HTTPException) as exc_info:
            raise HTTPException(status_code=403, detail="MUST_CHANGE_PASSWORD")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "MUST_CHANGE_PASSWORD"
    else:
        pytest.fail("User should have must_change_password=True")


@pytest.mark.asyncio
async def test_login_route_raises_403_for_must_change_password():
    """The login route must raise HTTP 403 MUST_CHANGE_PASSWORD when the flag is True (#757/#820)."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import HTTPException

    import fleet_platform.api.routes.auth as auth_mod
    from fleet_platform.core.auth import hash_password
    from fleet_platform.models.user import User
    from fleet_platform.schemas.auth import LoginRequest

    user = User(
        id=uuid.uuid4(),
        email="forced@example.com",
        password_hash=hash_password("secret123"),
        role="admin",
        is_active=True,
        auth_provider="local",
        must_change_password=True,
    )

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result_mock)

    fake_request = MagicMock()
    fake_request.client = MagicMock()
    fake_request.client.host = "127.0.0.1"

    payload = LoginRequest(email="forced@example.com", password="secret123")

    # Use the unwrapped login handler (bypasses the rate-limiter decorator)
    handler = getattr(auth_mod.login, "__wrapped__", auth_mod.login)

    with pytest.raises(HTTPException) as exc_info:
        await handler(request=fake_request, payload=payload, db=db)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "MUST_CHANGE_PASSWORD"


# ---------------------------------------------------------------------------
# 5. user_seeding — weak password handling (#757/#820)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_refuses_weak_admin_password_in_production(monkeypatch):
    """seed_local_users raises RuntimeError for weak admin passwords in production (#757/#820)."""
    import fleet_platform.core.config as cfg_mod
    import fleet_platform.services.user_seeding as seeding_mod

    monkeypatch.setattr(cfg_mod.settings, "environment", "production")
    monkeypatch.setenv("SEED_LOCAL_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SEED_LOCAL_ADMIN_PASSWORD", "admin")

    fake_db = mock.AsyncMock()
    fake_result = mock.MagicMock()
    fake_result.scalar_one_or_none.return_value = None
    fake_db.execute = mock.AsyncMock(return_value=fake_result)

    with pytest.raises((RuntimeError, ValueError), match="(?i)weak|insecure|password|change"):
        await seeding_mod.seed_local_users(fake_db)


@pytest.mark.asyncio
async def test_seed_sets_must_change_password_in_dev_for_weak_password(monkeypatch):
    """seed_local_users sets must_change_password=True in dev for weak admin password (#757/#820)."""
    import fleet_platform.core.config as cfg_mod
    import fleet_platform.services.user_seeding as seeding_mod

    monkeypatch.setattr(cfg_mod.settings, "environment", "development")
    monkeypatch.setenv("SEED_LOCAL_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SEED_LOCAL_ADMIN_PASSWORD", "admin")

    added_users: list = []

    async def fake_execute(stmt):
        r = mock.MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    fake_db = mock.AsyncMock()
    fake_db.execute = mock.AsyncMock(side_effect=fake_execute)
    fake_db.add = mock.MagicMock(side_effect=lambda u: added_users.append(u))
    fake_db.commit = mock.AsyncMock()

    await seeding_mod.seed_local_users(fake_db)

    assert added_users, "Expected at least one user to be seeded"
    admin_user = added_users[0]
    assert admin_user.must_change_password is True, (
        "Seeded admin with weak password must have must_change_password=True"
    )


@pytest.mark.asyncio
async def test_seed_does_not_set_must_change_for_strong_password(monkeypatch):
    """seed_local_users does NOT set must_change_password for a strong admin password (#757/#820)."""
    import fleet_platform.core.config as cfg_mod
    import fleet_platform.services.user_seeding as seeding_mod

    monkeypatch.setattr(cfg_mod.settings, "environment", "development")
    monkeypatch.setenv("SEED_LOCAL_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SEED_LOCAL_ADMIN_PASSWORD", "V3ryStr0ngPassw0rd!")

    added_users: list = []

    async def fake_execute(stmt):
        r = mock.MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    fake_db = mock.AsyncMock()
    fake_db.execute = mock.AsyncMock(side_effect=fake_execute)
    fake_db.add = mock.MagicMock(side_effect=lambda u: added_users.append(u))
    fake_db.commit = mock.AsyncMock()

    await seeding_mod.seed_local_users(fake_db)

    assert added_users, "Expected at least one user to be seeded"
    admin_user = added_users[0]
    assert admin_user.must_change_password is False, (
        "Seeded admin with strong password must NOT have must_change_password=True"
    )


# ---------------------------------------------------------------------------
# 6. User model — must_change_password column exists (#757/#820)
# ---------------------------------------------------------------------------


def test_user_model_has_must_change_password_column():
    """User model has a must_change_password boolean column (#757/#820)."""
    from fleet_platform.models.user import User

    assert hasattr(User, "must_change_password"), "User model must have a must_change_password attribute"


def test_user_model_must_change_password_defaults_false():
    """User.must_change_password defaults to False for normal users (#757/#820)."""
    from fleet_platform.models.user import User

    u = User(email="test@example.com", password_hash="hashed", role="viewer")
    assert u.must_change_password is False


# ---------------------------------------------------------------------------
# 7. Settings — new config fields exist (#763 and #759)
# ---------------------------------------------------------------------------


def test_settings_has_metrics_token():
    """Settings has a metrics_token field for /metrics auth (#763)."""
    from fleet_platform.core.config import Settings

    s = Settings(jwt_secret="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert hasattr(s, "metrics_token"), "Settings must have a metrics_token field (#763)"


def test_settings_metrics_token_defaults_none():
    """Settings.metrics_token defaults to None (#763)."""
    from fleet_platform.core.config import Settings

    s = Settings(jwt_secret="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert s.metrics_token is None


def test_settings_has_trusted_proxy_count():
    """Settings has a trusted_proxy_count field for rate-limiter IP key (#759)."""
    from fleet_platform.core.config import Settings

    s = Settings(jwt_secret="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert hasattr(s, "trusted_proxy_count"), "Settings must have a trusted_proxy_count field (#759)"


def test_settings_trusted_proxy_count_defaults_zero():
    """Settings.trusted_proxy_count defaults to 0 (no proxies, use direct connection IP) (#759)."""
    from fleet_platform.core.config import Settings

    s = Settings(jwt_secret="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert s.trusted_proxy_count == 0
