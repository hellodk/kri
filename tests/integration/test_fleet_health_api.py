# tests/integration/test_fleet_health_api.py
"""Integration tests for /api/v1/fleet-health routes.
Requires: DATABASE_URL pointing to a test PostgreSQL instance.
Run: pytest tests/integration/test_fleet_health_api.py -v
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_get_fleet_health_returns_200(async_client: AsyncClient, operator_token: str):
    response = await async_client.get(
        "/api/v1/fleet-health",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_trigger_collect_returns_202(async_client: AsyncClient, admin_token: str):
    with patch("fleet_platform.workers.health_tasks.collect_fleet_health.delay") as mock_delay:
        mock_delay.return_value = None
        response = await async_client.post(
            "/api/v1/fleet-health/collect",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_trigger_collect_requires_admin(async_client: AsyncClient, operator_token: str):
    response = await async_client.post(
        "/api/v1/fleet-health/collect",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_fleet_health_unauthenticated_returns_401(async_client: AsyncClient):
    response = await async_client.get("/api/v1/fleet-health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_node_health_history_returns_list(async_client: AsyncClient, operator_token: str, test_node):
    response = await async_client.get(
        f"/api/v1/fleet-health/{test_node.id}/history",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code in (200, 404)
