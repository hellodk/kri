# tests/integration/test_ingest_process_stats.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node
from fleet_platform.models.node_process_stat import NodeProcessStat
from fleet_platform.schemas.ingest import MAX_PROCESSES_PER_PAYLOAD


@pytest.fixture
async def registered_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="proc-test-01.local",
        hostname="proc-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="unknown",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node, token
    await db_session.execute(
        NodeProcessStat.__table__.delete().where(NodeProcessStat.node_id == node.id)
    )
    await db_session.delete(node)
    await db_session.commit()


def _proc(pid: int) -> dict:
    return {
        "pid": pid,
        "name": "exo",
        "cmdline": "/usr/bin/python exo",
        "cpu_pct": 12.5,
        "mem_rss_bytes": 2_147_483_648,
        "mem_pct": 6.25,
        "num_threads": 8,
        "status": "running",
        "username": "dk",
        "io_read_bytes": 1024,
        "io_write_bytes": 2048,
        "is_llm": True,
    }


async def _count_rows(db_session: AsyncSession, node_id) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(NodeProcessStat).where(NodeProcessStat.node_id == node_id)
    )
    return int(result.scalar_one())


async def test_process_stats_inserts_rows(client: AsyncClient, registered_node, db_session):
    node, token = registered_node
    resp = await client.post(
        "/api/v1/ingest/process_stats",
        json={"minion_id": node.minion_id, "processes": [_proc(1), _proc(2), _proc(3)]},
        headers={"X-Node-Token": token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["rows"] == 3
    assert await _count_rows(db_session, node.id) == 3


async def test_process_stats_invalid_token_returns_401(client: AsyncClient, registered_node):
    node, _ = registered_node
    resp = await client.post(
        "/api/v1/ingest/process_stats",
        json={"minion_id": node.minion_id, "processes": [_proc(1)]},
        headers={"X-Node-Token": "wrong-token"},
    )
    assert resp.status_code == 401


async def test_process_stats_missing_token_returns_401(client: AsyncClient, registered_node):
    node, _ = registered_node
    resp = await client.post(
        "/api/v1/ingest/process_stats",
        json={"minion_id": node.minion_id, "processes": [_proc(1)]},
    )
    assert resp.status_code == 401


async def test_process_stats_unknown_minion_returns_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/ingest/process_stats",
        json={"minion_id": "ghost.local", "processes": [_proc(1)]},
        headers={"X-Node-Token": "any-token"},
    )
    assert resp.status_code == 404


async def test_process_stats_over_cap_truncates_and_logs(
    client: AsyncClient, registered_node, db_session, caplog
):
    node, token = registered_node
    overflow = 25
    procs = [_proc(i) for i in range(MAX_PROCESSES_PER_PAYLOAD + overflow)]
    with caplog.at_level("WARNING"):
        resp = await client.post(
            "/api/v1/ingest/process_stats",
            json={"minion_id": node.minion_id, "processes": procs},
            headers={"X-Node-Token": token},
        )
    assert resp.status_code == 200
    assert resp.json()["rows"] == MAX_PROCESSES_PER_PAYLOAD
    assert await _count_rows(db_session, node.id) == MAX_PROCESSES_PER_PAYLOAD
    # Overflow must be logged — no silent truncation.
    assert any("exceeded cap" in r.message or "dropped" in r.message for r in caplog.records)
