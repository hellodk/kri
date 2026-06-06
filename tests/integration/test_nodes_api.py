# tests/integration/test_nodes_api.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node, Tag


@pytest.fixture
async def two_nodes(db_session: AsyncSession):
    token_a = secrets.token_urlsafe(32)
    token_b = secrets.token_urlsafe(32)
    node_a = Node(
        minion_id="api-node-a.local",
        hostname="api-node-a",
        node_token_hash=hash_password(token_a),
        first_seen_at=datetime.now(UTC),
        status="online",
        drift_score=10,
    )
    node_b = Node(
        minion_id="api-node-b.local",
        hostname="api-node-b",
        node_token_hash=hash_password(token_b),
        first_seen_at=datetime.now(UTC),
        status="offline",
        drift_score=55,
    )
    db_session.add_all([node_a, node_b])
    await db_session.commit()
    await db_session.refresh(node_a)
    await db_session.refresh(node_b)

    tag = Tag(node_id=node_a.id, key="env", value="prod", created_at=datetime.now(UTC))
    db_session.add(tag)
    await db_session.commit()

    yield node_a, node_b

    await db_session.delete(node_a)
    await db_session.delete(node_b)
    await db_session.commit()


async def test_list_nodes_returns_200(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2


async def test_list_nodes_filter_by_status(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes?status=online")
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(n["status"] == "online" for n in items)


async def test_list_nodes_filter_by_tag(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes?tag=env:prod")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert any(n["hostname"] == "api-node-a" for n in items)


async def test_list_nodes_pagination(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes?page=1&per_page=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["per_page"] == 1


async def test_get_node_detail(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.get(f"/api/v1/nodes/{node_a.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["minion_id"] == "api-node-a.local"
    assert "cpu_cores" in data
    assert "node_token_hash" not in data  # must never be exposed


async def test_get_node_not_found(admin_client: AsyncClient):
    import uuid

    response = await admin_client.get(f"/api/v1/nodes/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_nodes_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/nodes")
    assert response.status_code == 401


async def test_get_node_requires_auth(client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await client.get(f"/api/v1/nodes/{node_a.id}")
    assert response.status_code == 401


async def test_get_node_facts_returns_200(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.get(f"/api/v1/nodes/{node_a.id}/facts")
    assert response.status_code == 200
    assert "grains" in response.json()


async def test_add_tag_to_node(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.post(
        f"/api/v1/nodes/{node_a.id}/tags",
        json={"key": "team", "value": "mobile"},
    )
    assert response.status_code == 201
    assert response.json()["key"] == "team"


async def test_add_tag_requires_operator(viewer_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await viewer_client.post(
        f"/api/v1/nodes/{node_a.id}/tags",
        json={"key": "team", "value": "mobile"},
    )
    assert response.status_code == 403


async def test_delete_tag_from_node(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    # The env:prod tag was added in the fixture
    response = await admin_client.delete(f"/api/v1/nodes/{node_a.id}/tags/env")
    assert response.status_code == 204


async def test_delete_nonexistent_tag_returns_404(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.delete(f"/api/v1/nodes/{node_a.id}/tags/nonexistent-key")
    assert response.status_code == 404


async def test_per_page_capped_at_200(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/nodes?per_page=9999")
    assert r.status_code == 422


async def test_per_page_zero_rejected(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/nodes?per_page=0")
    assert r.status_code == 422


async def test_page_zero_rejected(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/nodes?page=0")
    assert r.status_code == 422
