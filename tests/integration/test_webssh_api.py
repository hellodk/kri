# tests/integration/test_webssh_api.py
"""Integration tests for the WebSSH routes.

The WebSocket endpoint (/api/v1/ssh/session/{node_id}) is tested at the
auth layer using Starlette's synchronous TestClient (which supports WS).

The REST endpoints (session list, recording, events) are tested normally
via the AsyncClient fixtures from conftest.
"""

import uuid

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

pytestmark = pytest.mark.asyncio


# ── WebSocket auth layer ───────────────────────────────────────────────


async def test_webssh_without_token_closes_4001(app_with_test_db):
    """WS connection without a token must be closed with code 4001."""
    node_id = uuid.uuid4()
    with TestClient(app_with_test_db) as tc:
        # raise_on_disconnect is not supported in starlette 1.x — omit it.
        # The server sends a close frame normally; no exception is raised.
        with tc.websocket_connect(f"/api/v1/ssh/session/{node_id}") as ws:
            data = ws.receive()
            assert data.get("type") == "websocket.close"
            assert data.get("code") == 4001


async def test_webssh_with_invalid_token_closes_4001(app_with_test_db):
    """WS connection with an invalid JWT must be closed with code 4001."""
    node_id = uuid.uuid4()
    with TestClient(app_with_test_db) as tc:
        with tc.websocket_connect(f"/api/v1/ssh/session/{node_id}?token=garbage") as ws:
            data = ws.receive()
            assert data.get("type") == "websocket.close"
            assert data.get("code") == 4001


async def test_webssh_valid_token_unknown_node_closes_4004(app_with_test_db, admin_token):
    """Valid JWT but non-existent node must close with 4004."""
    node_id = uuid.uuid4()
    with TestClient(app_with_test_db) as tc:
        with tc.websocket_connect(f"/api/v1/ssh/session/{node_id}?token={admin_token}") as ws:
            data = ws.receive()
            assert data.get("type") == "websocket.close"
            assert data.get("code") == 4004


# ── GET /api/v1/ssh/sessions ─────────────────────────────────────────


async def test_list_sessions_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/ssh/sessions")
    assert resp.status_code == 401


async def test_list_sessions_forbidden_for_viewer(viewer_client: AsyncClient):
    resp = await viewer_client.get("/api/v1/ssh/sessions")
    assert resp.status_code == 403


async def test_list_sessions_operator_allowed(operator_client: AsyncClient):
    resp = await operator_client.get("/api/v1/ssh/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_list_sessions_returns_200(admin_client: AsyncClient):
    resp = await admin_client.get("/api/v1/ssh/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json()["items"], list)


# ── GET /api/v1/ssh/sessions/{id}/recording ──────────────────────────


async def test_get_recording_requires_auth(client: AsyncClient):
    resp = await client.get(f"/api/v1/ssh/sessions/{uuid.uuid4()}/recording")
    assert resp.status_code == 401


async def test_get_recording_nonexistent_session_returns_empty(admin_client: AsyncClient):
    """A non-existent session ID returns 200 with empty chunks (no session exists)."""
    resp = await admin_client.get(f"/api/v1/ssh/sessions/{uuid.uuid4()}/recording")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunks"] == []


# ── GET /api/v1/ssh/events ────────────────────────────────────────────


async def test_list_events_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/ssh/events")
    assert resp.status_code == 401


async def test_list_events_forbidden_for_viewer(viewer_client: AsyncClient):
    resp = await viewer_client.get("/api/v1/ssh/events")
    assert resp.status_code == 403


async def test_list_events_returns_200(admin_client: AsyncClient):
    resp = await admin_client.get("/api/v1/ssh/events")
    assert resp.status_code == 200
    assert "items" in resp.json()
