# tests/integration/test_fleet_overview.py
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


async def test_fleet_overview_returns_200(admin_client: AsyncClient, app_with_test_db):
    app_with_test_db._test_mock_redis.get.return_value = None
    response = await admin_client.get("/api/v1/fleet/overview")
    assert response.status_code == 200


async def test_fleet_overview_shape(admin_client: AsyncClient, app_with_test_db):
    app_with_test_db._test_mock_redis.get.return_value = None
    response = await admin_client.get("/api/v1/fleet/overview")
    data = response.json()
    for field in ("total_nodes", "online", "stale", "offline", "avg_drift_score",
                  "nodes_clean", "nodes_low", "nodes_medium", "nodes_high",
                  "nodes_critical", "last_updated"):
        assert field in data, f"missing field: {field}"


async def test_fleet_overview_serves_cache(admin_client: AsyncClient, app_with_test_db):
    cached = json.dumps({
        "total_nodes": 42, "online": 40, "stale": 1, "offline": 1, "unknown": 0,
        "avg_drift_score": 7, "nodes_clean": 35, "nodes_low": 4, "nodes_medium": 2,
        "nodes_high": 1, "nodes_critical": 0,
        "last_updated": datetime.now(UTC).isoformat(),
    })
    app_with_test_db._test_mock_redis.get.return_value = cached
    response = await admin_client.get("/api/v1/fleet/overview")
    # Reset to cache miss for subsequent tests
    app_with_test_db._test_mock_redis.get.return_value = None
    assert response.status_code == 200
    assert response.json()["total_nodes"] == 42


async def test_fleet_overview_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/fleet/overview")
    assert response.status_code == 401
