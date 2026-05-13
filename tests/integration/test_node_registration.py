# tests/integration/test_node_registration.py
import pytest
from httpx import AsyncClient


async def test_register_node_returns_token(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-node-01.local", "hostname": "test-node-01"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "node_id" in data
    assert "token" in data
    assert len(data["token"]) >= 32
    assert "message" in data


async def test_register_node_viewer_forbidden(viewer_client: AsyncClient):
    response = await viewer_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-node-02.local"},
    )
    assert response.status_code == 403


async def test_register_duplicate_minion_id_returns_409(admin_client: AsyncClient):
    await admin_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-dup.local"},
    )
    response = await admin_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-dup.local"},
    )
    assert response.status_code == 409


async def test_register_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-node-03.local"},
    )
    assert response.status_code == 401
