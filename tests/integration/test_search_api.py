# tests/integration/test_search_api.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node, Tag


@pytest.fixture
async def searchable_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="searchme-01.local",
        hostname="searchme-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    tag = Tag(node_id=node.id, key="role", value="searchable", created_at=datetime.now(UTC))
    db_session.add(tag)
    await db_session.commit()
    yield node
    await db_session.delete(node)
    await db_session.commit()


async def test_search_by_hostname(admin_client: AsyncClient, searchable_node):
    response = await admin_client.get("/api/v1/search?q=searchme")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert any(n["hostname"] == "searchme-01" for n in data["nodes"])


async def test_search_requires_min_3_chars(admin_client: AsyncClient):
    response = await admin_client.get("/api/v1/search?q=ab")
    assert response.status_code == 422


async def test_search_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/search?q=searchme")
    assert response.status_code == 401
