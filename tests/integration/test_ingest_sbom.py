# tests/integration/test_ingest_sbom.py
import json
import secrets
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node


@pytest.fixture
async def sbom_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="sbom-test-01.local",
        hostname="sbom-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node, token
    await db_session.delete(node)
    await db_session.commit()


_SAMPLE_CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.4",
    "version": 1,
    "components": [
        {
            "type": "library",
            "name": "openssl",
            "version": "3.3.0",
            "purl": "pkg:brew/openssl@3.3.0",
        }
    ],
}


async def test_sbom_ingest_returns_202(client: AsyncClient, sbom_node):
    node, token = sbom_node
    # #749: dispatch by task name via celery_app.send_task, not index_sbom.delay().
    with patch("fleet_platform.api.routes.ingest.celery_app.send_task"):
        response = await client.post(
            f"/api/v1/ingest/sbom/{node.minion_id}",
            content=json.dumps(_SAMPLE_CYCLONEDX),
            headers={
                "X-Node-Token": token,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert "node_id" in data


async def test_sbom_ingest_queues_index_task(client: AsyncClient, sbom_node):
    node, token = sbom_node
    with patch("fleet_platform.api.routes.ingest.celery_app.send_task") as mock_send:
        await client.post(
            f"/api/v1/ingest/sbom/{node.minion_id}",
            content=json.dumps(_SAMPLE_CYCLONEDX),
            headers={"X-Node-Token": token, "Content-Type": "application/json"},
        )
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        assert args[0] == "fleet_platform.workers.sbom_tasks.index_sbom"
        assert kwargs["kwargs"]["node_id"] == str(node.id)


async def test_sbom_ingest_invalid_token_returns_401(client: AsyncClient, sbom_node):
    node, _ = sbom_node
    response = await client.post(
        f"/api/v1/ingest/sbom/{node.minion_id}",
        content=json.dumps(_SAMPLE_CYCLONEDX),
        headers={"X-Node-Token": "bad-token", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


async def test_sbom_ingest_unknown_minion_returns_404(client: AsyncClient):
    response = await client.post(
        "/api/v1/ingest/sbom/ghost-node.local",
        content=json.dumps(_SAMPLE_CYCLONEDX),
        headers={"X-Node-Token": "any", "Content-Type": "application/json"},
    )
    assert response.status_code == 404
