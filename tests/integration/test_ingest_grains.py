# tests/integration/test_ingest_grains.py
import secrets
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node


@pytest.fixture
async def registered_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="ingest-test-01.local",
        hostname="ingest-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="unknown",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node, token
    await db_session.delete(node)
    await db_session.commit()


_SAMPLE_GRAINS = {
    "id": "ingest-test-01.local",
    "os": "MacOS",
    "osrelease": "14.4.1",
    "osbuild": "23E224",
    "productname": "Mac mini",
    "cpuarch": "arm64",
    "num_cpus": 10,
    "mem_total": 32768,
    "ip4_interfaces": {"en0": ["192.168.1.101"]},
    "ip_interfaces": {"en0": {"inet": ["192.168.1.101"]}},
}


async def test_grain_ingest_returns_200(client: AsyncClient, registered_node):
    node, token = registered_node
    with patch("fleet_platform.api.routes.ingest.compute_drift"):
        response = await client.post(
            "/api/v1/ingest/grains",
            json={"minion_id": node.minion_id, "grains": _SAMPLE_GRAINS},
            headers={"X-Node-Token": token},
        )
    assert response.status_code == 200


async def test_grain_ingest_queues_drift_task(client: AsyncClient, registered_node):
    node, token = registered_node
    with patch("fleet_platform.api.routes.ingest.compute_drift") as mock_task:
        await client.post(
            "/api/v1/ingest/grains",
            json={"minion_id": node.minion_id, "grains": _SAMPLE_GRAINS},
            headers={"X-Node-Token": token},
        )
        mock_task.delay.assert_called_once_with(str(node.id))


async def test_grain_ingest_invalid_token_returns_401(client: AsyncClient, registered_node):
    node, _ = registered_node
    response = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": node.minion_id, "grains": {}},
        headers={"X-Node-Token": "wrong-token"},
    )
    assert response.status_code == 401


async def test_grain_ingest_unknown_minion_returns_404(client: AsyncClient):
    response = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": "ghost.local", "grains": {}},
        headers={"X-Node-Token": "any-token"},
    )
    assert response.status_code == 404


async def test_grain_ingest_missing_token_returns_401(client: AsyncClient, registered_node):
    node, _ = registered_node
    response = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": node.minion_id, "grains": _SAMPLE_GRAINS},
    )
    assert response.status_code == 401
