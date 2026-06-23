# tests/integration/test_process_stats_ingest.py
"""Integration tests for POST /api/v1/ingest/process_stats (#598).

These tests require a live PostgreSQL/TimescaleDB instance. They are NOT run
in the unit-test gate — they run at merge time or when the developer explicitly
invokes `pytest tests/integration/test_process_stats_ingest.py`.
"""

import secrets
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def registered_node_client(app_with_test_db, db_session: AsyncSession):
    """A Node with a known X-Node-Token, plus a client preconfigured with it."""
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="integration-test-node",
        hostname="integration-test-node",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"X-Node-Token": token},
    ) as ac:
        yield ac
    await db_session.delete(node)
    await db_session.commit()


async def test_ingest_process_stats_missing_token(client: AsyncClient):
    """401 when X-Node-Token header is absent."""
    payload = {
        "minion_id": "test-node",
        "processes": [{"pid": 1, "name": "launchd"}],
    }
    resp = await client.post("/api/v1/ingest/process_stats", json=payload)
    assert resp.status_code == 401


async def test_ingest_process_stats_unknown_node(client: AsyncClient):
    """404 when minion_id is not registered."""
    payload = {
        "minion_id": f"ghost-{uuid.uuid4()}",
        "processes": [{"pid": 42, "name": "unknown_proc"}],
    }
    resp = await client.post(
        "/api/v1/ingest/process_stats",
        json=payload,
        headers={"X-Node-Token": "bad-token"},
    )
    assert resp.status_code == 404


async def test_ingest_process_stats_happy_path(registered_node_client: AsyncClient):
    """200 + correct row count for a valid authenticated request.

    `registered_node_client` is a fixture that creates a Node with a known
    token and returns an AsyncClient configured with the X-Node-Token header.
    """
    payload = {
        "minion_id": "integration-test-node",
        "processes": [
            {"pid": 1, "name": "launchd"},
            {"pid": 100, "name": "ollama", "is_llm": True, "cpu_pct": 45.2},
        ],
    }
    resp = await registered_node_client.post("/api/v1/ingest/process_stats", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["rows"] == 2
    assert data["dropped"] == 0


async def test_ingest_process_stats_cap_at_250(registered_node_client: AsyncClient):
    """Payloads with >250 processes are capped; dropped count is returned."""
    procs = [{"pid": i, "name": f"proc_{i}"} for i in range(300)]
    payload = {"minion_id": "integration-test-node", "processes": procs}
    resp = await registered_node_client.post("/api/v1/ingest/process_stats", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["rows"] == 250
    assert data["dropped"] == 50


async def test_ingest_process_stats_empty_processes(registered_node_client: AsyncClient):
    """Empty processes list is accepted; rows == 0, dropped == 0."""
    payload = {"minion_id": "integration-test-node", "processes": []}
    resp = await registered_node_client.post("/api/v1/ingest/process_stats", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["rows"] == 0
    assert data["dropped"] == 0
