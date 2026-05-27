# tests/integration/test_vnc_api.py
"""Integration tests for the VNC WebSocket endpoint.

The VNC route is a pure WebSocket endpoint — there is no REST API surface
to call. The integration tests verify the *auth layer* by attempting HTTP
upgrade requests (or direct WS handshakes that the ASGI test client can
exercise) and confirming the correct close codes are returned.

Strategy: use the ASGI transport's WebSocket support via starlette's
TestClient or httpx. Because httpx AsyncClient does not natively support
WebSocket upgrades, we assert on the HTTP 401/403 behaviour at the upgrade
layer and test the WS auth path via the same conftest app.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.asyncio


# ── HTTP upgrade — unauthenticated ────────────────────────────────────


async def test_vnc_upgrade_without_token_closes_4001(app_with_test_db):
    """WS connection without a token must be closed with code 4001.

    VNC checks feature flag before auth — mock flag as enabled so the
    auth check runs and can reject the unauthenticated connection with 4001.
    """
    node_id = uuid.uuid4()
    with patch(
        "fleet_platform.api.routes.vnc.get_setting",
        new=AsyncMock(return_value="true"),
    ):
        with TestClient(app_with_test_db) as tc:
            with tc.websocket_connect(
                f"/api/v1/vnc/session/{node_id}",
                raise_on_disconnect=False,
            ) as ws:
                data = ws.receive()
                assert data.get("type") == "websocket.close"
                assert data.get("code") == 4001


async def test_vnc_upgrade_with_invalid_token_closes_4001(app_with_test_db):
    """WS connection with a garbage token must be closed with code 4001.

    VNC checks feature flag before auth — mock flag as enabled so the
    auth check runs and rejects the invalid token with 4001.
    """
    node_id = uuid.uuid4()
    with patch(
        "fleet_platform.api.routes.vnc.get_setting",
        new=AsyncMock(return_value="true"),
    ):
        with TestClient(app_with_test_db) as tc:
            with tc.websocket_connect(
                f"/api/v1/vnc/session/{node_id}?token=not-a-valid-jwt",
                raise_on_disconnect=False,
            ) as ws:
                data = ws.receive()
                assert data.get("type") == "websocket.close"
                assert data.get("code") == 4001


async def test_vnc_upgrade_valid_token_unknown_node_closes_4004(
    app_with_test_db, admin_token
):
    """Valid JWT but non-existent node must be closed with code 4004."""
    node_id = uuid.uuid4()
    # VNC checks the feature flag first — mock it as enabled
    with patch(
        "fleet_platform.api.routes.vnc.get_setting",
        new=AsyncMock(return_value="true"),
    ):
        with TestClient(app_with_test_db) as tc:
            with tc.websocket_connect(
                f"/api/v1/vnc/session/{node_id}?token={admin_token}",
                raise_on_disconnect=False,
            ) as ws:
                data = ws.receive()
                assert data.get("type") == "websocket.close"
                assert data.get("code") == 4004


async def test_vnc_feature_flag_disabled_closes_4003(app_with_test_db, admin_token):
    """When the VNC feature flag is off, the connection must close with 4003."""
    node_id = uuid.uuid4()
    with patch(
        "fleet_platform.api.routes.vnc.get_setting",
        new=AsyncMock(return_value="false"),
    ):
        with TestClient(app_with_test_db) as tc:
            with tc.websocket_connect(
                f"/api/v1/vnc/session/{node_id}?token={admin_token}",
                raise_on_disconnect=False,
            ) as ws:
                data = ws.receive()
                assert data.get("type") == "websocket.close"
                assert data.get("code") == 4003
