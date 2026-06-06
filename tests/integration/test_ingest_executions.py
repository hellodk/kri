# tests/integration/test_ingest_executions.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node


@pytest.fixture
async def exec_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="exec-test-01.local",
        hostname="exec-test-01",
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


async def test_execution_ingest_returns_200(client: AsyncClient, exec_node):
    node, token = exec_node
    response = await client.post(
        "/api/v1/ingest/executions",
        json={
            "minion_id": node.minion_id,
            "jid": "20260512100000123456",
            "return_data": {"cmd.run": "ok"},
            "fun": "cmd.run",
            "retcode": 0,
            "success": True,
        },
        headers={"X-Node-Token": token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "job_id" in data


async def test_execution_ingest_creates_job_and_result(client: AsyncClient, exec_node, db_session: AsyncSession):
    from sqlalchemy import select

    from fleet_platform.models.execution import ExecutionJob, ExecutionResult

    node, token = exec_node
    await client.post(
        "/api/v1/ingest/executions",
        json={
            "minion_id": node.minion_id,
            "jid": "20260512100000999999",
            "return_data": {"test.ping": True},
            "fun": "test.ping",
            "retcode": 0,
        },
        headers={"X-Node-Token": token},
    )

    job = (
        await db_session.execute(select(ExecutionJob).where(ExecutionJob.salt_jid == "20260512100000999999"))
    ).scalar_one_or_none()
    assert job is not None
    assert job.status == "completed"

    result = (
        await db_session.execute(select(ExecutionResult).where(ExecutionResult.job_id == job.id))
    ).scalar_one_or_none()
    assert result is not None
    assert result.node_id == node.id


async def test_execution_ingest_invalid_token_returns_401(client: AsyncClient, exec_node):
    node, _ = exec_node
    response = await client.post(
        "/api/v1/ingest/executions",
        json={"minion_id": node.minion_id, "jid": "123", "return_data": {}, "fun": "test.ping"},
        headers={"X-Node-Token": "bad-token"},
    )
    assert response.status_code == 401
