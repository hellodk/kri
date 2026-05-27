# tests/integration/test_node_secrets_api.py
"""Integration tests for the node secrets API routes.

Secrets are CRUD-managed under /api/v1/nodes/{node_id}/secrets.
Pillar file writes are patched to avoid filesystem dependencies.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# Patch targets for the filesystem-touching helpers
_WRITE_PILLAR = "fleet_platform.api.routes.node_secrets.node_secrets_svc.write_node_pillar"


async def _create_node(admin_client: AsyncClient, minion_id: str | None = None) -> str:
    """Helper: create a node via the API and return its UUID string."""
    mid = minion_id or f"secrets-test-node-{uuid.uuid4().hex[:6]}.local"
    resp = await admin_client.post(
        "/api/v1/nodes",
        json={"minion_id": mid, "hostname": mid},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _delete_node(admin_client: AsyncClient, node_id: str) -> None:
    await admin_client.delete(f"/api/v1/nodes/{node_id}")


# ── GET /api/v1/nodes/{node_id}/secrets ──────────────────────────────


async def test_list_node_secrets_requires_auth(client: AsyncClient):
    """Unauthenticated request must get 401."""
    resp = await client.get(f"/api/v1/nodes/{uuid.uuid4()}/secrets")
    assert resp.status_code == 401


async def test_list_node_secrets_nonexistent_node_404(admin_client: AsyncClient):
    resp = await admin_client.get(f"/api/v1/nodes/{uuid.uuid4()}/secrets")
    assert resp.status_code == 404


async def test_list_node_secrets_viewer_allowed(
    admin_client: AsyncClient, viewer_client: AsyncClient
):
    """Any authenticated user may list node secrets."""
    node_id = await _create_node(admin_client)
    resp = await viewer_client.get(f"/api/v1/nodes/{node_id}/secrets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    await _delete_node(admin_client, node_id)


async def test_list_node_secrets_empty_on_new_node(admin_client: AsyncClient):
    node_id = await _create_node(admin_client)
    resp = await admin_client.get(f"/api/v1/nodes/{node_id}/secrets")
    assert resp.status_code == 200
    assert resp.json() == []
    await _delete_node(admin_client, node_id)


# ── PUT /api/v1/nodes/{node_id}/secrets/{key} ─────────────────────────


async def test_upsert_node_secret_requires_auth(client: AsyncClient):
    resp = await client.put(
        f"/api/v1/nodes/{uuid.uuid4()}/secrets/MY_KEY",
        json={"value": "secret-val"},
    )
    assert resp.status_code == 401


async def test_upsert_node_secret_requires_operator(
    admin_client: AsyncClient, viewer_client: AsyncClient
):
    """Viewer role must be rejected with 403."""
    node_id = await _create_node(admin_client)
    resp = await viewer_client.put(
        f"/api/v1/nodes/{node_id}/secrets/MY_KEY",
        json={"value": "secret-val"},
    )
    assert resp.status_code == 403
    await _delete_node(admin_client, node_id)


async def test_upsert_node_secret_nonexistent_node_404(admin_client: AsyncClient):
    with patch(_WRITE_PILLAR, new=AsyncMock()):
        resp = await admin_client.put(
            f"/api/v1/nodes/{uuid.uuid4()}/secrets/MY_KEY",
            json={"value": "secret-val"},
        )
    assert resp.status_code == 404


async def test_upsert_node_secret_happy_path(admin_client: AsyncClient):
    """PUT creates a secret and returns its metadata (value never returned)."""
    node_id = await _create_node(admin_client)

    with patch(_WRITE_PILLAR, new=AsyncMock()):
        resp = await admin_client.put(
            f"/api/v1/nodes/{node_id}/secrets/DB_PASSWORD",
            json={"value": "s3cr3t", "description": "database password"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "DB_PASSWORD"
    assert data["description"] == "database password"
    assert "created_at" in data
    # Value is never echoed back
    assert "value" not in data

    await _delete_node(admin_client, node_id)


async def test_upsert_node_secret_update_existing(admin_client: AsyncClient):
    """PUT on an existing key updates the secret (upsert semantics)."""
    node_id = await _create_node(admin_client)

    with patch(_WRITE_PILLAR, new=AsyncMock()):
        r1 = await admin_client.put(
            f"/api/v1/nodes/{node_id}/secrets/API_TOKEN",
            json={"value": "token-v1"},
        )
        assert r1.status_code == 200

        r2 = await admin_client.put(
            f"/api/v1/nodes/{node_id}/secrets/API_TOKEN",
            json={"value": "token-v2"},
        )
    assert r2.status_code == 200
    assert r2.json()["key"] == "API_TOKEN"

    # Only one entry in the list
    list_resp = await admin_client.get(f"/api/v1/nodes/{node_id}/secrets")
    keys = [s["key"] for s in list_resp.json()]
    assert keys.count("API_TOKEN") == 1

    await _delete_node(admin_client, node_id)


# ── DELETE /api/v1/nodes/{node_id}/secrets/{key} ─────────────────────


async def test_delete_node_secret_requires_auth(client: AsyncClient):
    resp = await client.delete(f"/api/v1/nodes/{uuid.uuid4()}/secrets/KEY")
    assert resp.status_code == 401


async def test_delete_node_secret_requires_operator(
    admin_client: AsyncClient, viewer_client: AsyncClient
):
    node_id = await _create_node(admin_client)
    resp = await viewer_client.delete(f"/api/v1/nodes/{node_id}/secrets/KEY")
    assert resp.status_code == 403
    await _delete_node(admin_client, node_id)


async def test_delete_node_secret_not_found(admin_client: AsyncClient):
    """Deleting a key that does not exist returns 404."""
    node_id = await _create_node(admin_client)
    with patch(_WRITE_PILLAR, new=AsyncMock()):
        resp = await admin_client.delete(
            f"/api/v1/nodes/{node_id}/secrets/DOES_NOT_EXIST"
        )
    assert resp.status_code == 404
    await _delete_node(admin_client, node_id)


async def test_delete_node_secret_happy_path(admin_client: AsyncClient):
    """Create a secret then delete it — it disappears from the list."""
    node_id = await _create_node(admin_client)

    with patch(_WRITE_PILLAR, new=AsyncMock()):
        await admin_client.put(
            f"/api/v1/nodes/{node_id}/secrets/TO_DELETE",
            json={"value": "bye"},
        )
        del_resp = await admin_client.delete(
            f"/api/v1/nodes/{node_id}/secrets/TO_DELETE"
        )
    assert del_resp.status_code == 204

    list_resp = await admin_client.get(f"/api/v1/nodes/{node_id}/secrets")
    keys = [s["key"] for s in list_resp.json()]
    assert "TO_DELETE" not in keys

    await _delete_node(admin_client, node_id)
