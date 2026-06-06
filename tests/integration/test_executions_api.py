# tests/integration/test_executions_api.py
import secrets
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.models.node import Node


@pytest.fixture
async def job_with_result(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="exec-node-01.local",
        hostname="exec-node-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    job = ExecutionJob(
        salt_jid="20260513100000123456",
        type="highstate",
        target_type="node",
        target_id=node.id,
        triggered_by="salt",
        status="complete",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    result = ExecutionResult(
        job_id=job.id,
        node_id=node.id,
        status="success",
        exit_code=0,
        changes={"pkg": "installed"},
        completed_at=datetime.now(UTC),
    )
    db_session.add(result)
    await db_session.commit()
    await db_session.refresh(result)

    yield job, result, node

    await db_session.delete(result)
    await db_session.flush()
    await db_session.delete(job)
    await db_session.delete(node)
    await db_session.commit()


async def test_list_executions(admin_client: AsyncClient, job_with_result):
    response = await admin_client.get("/api/v1/executions")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


async def test_list_executions_filter_by_status(admin_client: AsyncClient, job_with_result):
    response = await admin_client.get("/api/v1/executions?status=complete")
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(j["status"] == "complete" for j in items)


async def test_get_execution_job(admin_client: AsyncClient, job_with_result):
    job, _, _ = job_with_result
    response = await admin_client.get(f"/api/v1/executions/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["salt_jid"] == "20260513100000123456"
    assert data["type"] == "highstate"


async def test_get_execution_results(admin_client: AsyncClient, job_with_result):
    job, _, _ = job_with_result
    response = await admin_client.get(f"/api/v1/executions/{job.id}/results")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["status"] == "success"


async def test_get_execution_not_found(admin_client: AsyncClient):
    response = await admin_client.get(f"/api/v1/executions/{uuid.uuid4()}")
    assert response.status_code == 404
