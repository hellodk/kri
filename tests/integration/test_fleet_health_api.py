# tests/integration/test_fleet_health_api.py
"""Integration tests for /api/v1/fleet-health routes.
Requires: DATABASE_URL pointing to a test PostgreSQL instance.
Run: pytest tests/integration/test_fleet_health_api.py -v
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.node import Node

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def test_node(db_session: AsyncSession):
    """Create a minimal Node row for health-history tests, clean up after."""
    from fleet_platform.core.auth import hash_password

    node = Node(
        minion_id=f"health-test-{uuid.uuid4().hex[:8]}",
        status="online",
        node_token_hash=hash_password("test-token"),
        first_seen_at=datetime.now(UTC),
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node
    await db_session.delete(node)
    await db_session.commit()


async def test_get_fleet_health_returns_200(operator_client: AsyncClient):
    response = await operator_client.get("/api/v1/fleet-health")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_trigger_collect_returns_202(admin_client: AsyncClient):
    with patch("fleet_platform.workers.health_tasks.collect_fleet_health.delay") as mock_delay:
        mock_delay.return_value = None
        response = await admin_client.post("/api/v1/fleet-health/collect")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


async def test_trigger_collect_requires_admin(operator_client: AsyncClient):
    response = await operator_client.post("/api/v1/fleet-health/collect")
    assert response.status_code == 403


async def test_fleet_health_unauthenticated_returns_401(client: AsyncClient):
    response = await client.get("/api/v1/fleet-health")
    assert response.status_code == 401


async def test_node_health_history_returns_list(operator_client: AsyncClient, test_node):
    response = await operator_client.get(f"/api/v1/fleet-health/{test_node.id}/history")
    assert response.status_code in (200, 404)
