# tests/integration/test_salt_keys_api.py
"""Integration tests for the salt-keys API routes.

The routes manage minion keys through the default SaltMaster's salt-api
(rest_cherrypy) wheel client. Tests mock ``_get_default_master`` and
``run_wheel`` so no real salt-master is required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from fleet_platform.services.salt_api_client import SaltApiError

pytestmark = pytest.mark.asyncio

_ROUTE = "fleet_platform.api.routes.salt_keys"


def _master_mock():
    """Patch ``_get_default_master`` to return a configured master."""
    return patch(f"{_ROUTE}._get_default_master", new=AsyncMock(return_value=MagicMock()))


# ── GET /api/v1/salt/keys ─────────────────────────────────────────────


async def test_list_keys_requires_auth(client: AsyncClient):
    """Unauthenticated request must get 401."""
    resp = await client.get("/api/v1/salt/keys")
    assert resp.status_code == 401


async def test_list_keys_returns_grouped_result(admin_client: AsyncClient):
    """Authenticated request returns keys grouped by status."""
    wheel_data = {
        "minions": ["mac-accepted"],
        "minions_pre": ["mac-pending"],
        "minions_rejected": [],
        "minions_denied": [],
    }
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", return_value=wheel_data):
        resp = await admin_client.get("/api/v1/salt/keys")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("accepted", "pending", "rejected", "denied"):
        assert key in data
        assert isinstance(data[key], list)
    assert data["pending"] == ["mac-pending"]
    assert data["pending_count"] == 1
    assert data["degraded"] is False


async def test_list_keys_viewer_allowed(viewer_client: AsyncClient):
    """Viewer role may list keys (only requires authentication)."""
    empty = {"minions": [], "minions_pre": [], "minions_rejected": [], "minions_denied": []}
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", return_value=empty):
        resp = await viewer_client.get("/api/v1/salt/keys")
    assert resp.status_code == 200


async def test_list_keys_degraded_when_no_master(admin_client: AsyncClient):
    """With no salt-master configured the endpoint degrades gracefully (200)."""
    with patch(f"{_ROUTE}._get_default_master", new=AsyncMock(return_value=None)):
        resp = await admin_client.get("/api/v1/salt/keys")
    assert resp.status_code == 200
    assert resp.json()["degraded"] is True


# ── POST /api/v1/salt/keys/{minion_id}/accept ─────────────────────────


async def test_accept_key_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/salt/keys/mac-mini-01/accept")
    assert resp.status_code == 401


async def test_accept_key_requires_admin(viewer_client: AsyncClient):
    resp = await viewer_client.post("/api/v1/salt/keys/mac-mini-01/accept")
    assert resp.status_code == 403


async def test_accept_key_rejects_invalid_minion_id(admin_client: AsyncClient):
    """Minion IDs with path-traversal chars must be rejected with 422."""
    resp = await admin_client.post("/api/v1/salt/keys/../etc-passwd/accept")
    # FastAPI may return 422 or 404 depending on URL routing; either blocks the attack
    assert resp.status_code in (404, 422)


async def test_accept_key_salt_api_error_returns_502(admin_client: AsyncClient):
    """Wheel-client failures surface as HTTP 502."""
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("master unreachable")):
        resp = await admin_client.post("/api/v1/salt/keys/no-such-minion/accept")
    assert resp.status_code == 502


async def test_accept_key_happy_path(admin_client: AsyncClient):
    """A pending key is accepted via the wheel client."""
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", return_value={"data": {"return": True}}) as rw:
        resp = await admin_client.post("/api/v1/salt/keys/mac-mini-01/accept")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["minion_id"] == "mac-mini-01"
    rw.assert_called_once()


# ── POST /api/v1/salt/keys/{minion_id}/reject ─────────────────────────


async def test_reject_key_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/salt/keys/mac-mini-01/reject")
    assert resp.status_code == 401


async def test_reject_key_requires_admin(operator_client: AsyncClient):
    """Operator role is not sufficient — only admin may reject keys."""
    resp = await operator_client.post("/api/v1/salt/keys/mac-mini-01/reject")
    assert resp.status_code == 403


async def test_reject_key_salt_api_error_returns_502(admin_client: AsyncClient):
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("master unreachable")):
        resp = await admin_client.post("/api/v1/salt/keys/ghost/reject")
    assert resp.status_code == 502


async def test_reject_key_happy_path(admin_client: AsyncClient):
    """A key is rejected via the wheel client."""
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", return_value={"data": {"return": True}}) as rw:
        resp = await admin_client.post("/api/v1/salt/keys/bad-minion/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    rw.assert_called_once()


# ── DELETE /api/v1/salt/keys/{minion_id} ──────────────────────────────


async def test_delete_key_requires_auth(client: AsyncClient):
    resp = await client.delete("/api/v1/salt/keys/mac-mini-01")
    assert resp.status_code == 401


async def test_delete_key_requires_admin(operator_client: AsyncClient):
    resp = await operator_client.delete("/api/v1/salt/keys/mac-mini-01")
    assert resp.status_code == 403


async def test_delete_key_salt_api_error_returns_502(admin_client: AsyncClient):
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("master unreachable")):
        resp = await admin_client.delete("/api/v1/salt/keys/missing-minion")
    assert resp.status_code == 502


async def test_delete_key_happy_path(admin_client: AsyncClient):
    """Deletes a key via the wheel client."""
    with _master_mock(), patch(f"{_ROUTE}.run_wheel", return_value={"data": {"return": True}}) as rw:
        resp = await admin_client.delete("/api/v1/salt/keys/old-mac")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    rw.assert_called_once()
