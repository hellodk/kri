# tests/integration/test_drift_api.py
import secrets
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.node import Node


@pytest.fixture
async def node_with_drift(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="drift-test-01.local",
        hostname="drift-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
        drift_score=45,
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    baseline = DesiredStateBaseline(
        name="drift-test-baseline",
        target_type="global",
        git_commit_sha="abc1234",
        state_json={"packages": {"required": [{"name": "git"}]}},
    )
    db_session.add(baseline)
    await db_session.commit()
    await db_session.refresh(baseline)

    record = DriftRecord(
        node_id=node.id,
        baseline_id=baseline.id,
        computed_at=datetime.now(UTC),
        drift_score=45,
        missing_packages=[{"name": "node", "required_version": None}],
        extra_packages=[{"name": "teamviewer", "installed_version": "15.0"}],
        version_mismatches=[],
        service_drift=[],
        config_drift=[],
    )
    db_session.add(record)
    await db_session.commit()

    yield node, baseline, record

    await db_session.delete(record)
    await db_session.delete(baseline)
    await db_session.delete(node)
    await db_session.commit()


async def test_list_drift_returns_nodes(admin_client: AsyncClient, node_with_drift):
    response = await admin_client.get("/api/v1/drift")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    hostnames = [n["hostname"] for n in data["items"]]
    assert "drift-test-01" in hostnames


async def test_list_drift_filter_by_severity(admin_client: AsyncClient, node_with_drift):
    response = await admin_client.get("/api/v1/drift?severity=medium")
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(n["hostname"] == "drift-test-01" for n in items)


async def test_get_node_drift_latest(admin_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    response = await admin_client.get(f"/api/v1/drift/{node.id}/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["drift_score"] == 45
    assert len(data["missing_packages"]) == 1


async def test_get_node_drift_history(admin_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    response = await admin_client.get(f"/api/v1/drift/{node.id}/history")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


async def test_trigger_drift_compute_queues_task(admin_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    with patch("fleet_platform.api.routes.drift.compute_drift") as mock_task:
        response = await admin_client.post(f"/api/v1/drift/{node.id}/compute")
    assert response.status_code == 202
    mock_task.delay.assert_called_once_with(str(node.id))


async def test_drift_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/drift")
    assert response.status_code == 401


async def test_trigger_compute_requires_operator(viewer_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    response = await viewer_client.post(f"/api/v1/drift/{node.id}/compute")
    assert response.status_code == 403
