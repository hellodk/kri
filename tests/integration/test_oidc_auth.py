"""Integration tests for OIDC authentication endpoints."""
from httpx import AsyncClient


async def test_oidc_config_disabled_by_default(client: AsyncClient):
    r = await client.get("/api/v1/auth/oidc/config")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_oidc_login_returns_400_when_disabled(client: AsyncClient):
    r = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 400


async def test_oidc_callback_rejects_invalid_state(app_with_test_db, client: AsyncClient):
    # Ensure getdel returns None for any unknown state so the state check rejects it
    app_with_test_db._test_mock_redis.getdel.return_value = None
    r = await client.get("/api/v1/auth/oidc/callback?code=x&state=invalid-state")
    assert r.status_code == 400
    assert "state" in r.json()["detail"].lower()
