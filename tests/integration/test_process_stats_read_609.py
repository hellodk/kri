# tests/integration/test_process_stats_read_609.py
"""Integration tests for GET /api/v1/nodes/{node_id}/process_stats (#609).

These tests require a live PostgreSQL/TimescaleDB instance. They are NOT run
in the unit-test gate — they run at merge time or when the developer explicitly
invokes `pytest tests/integration/test_process_stats_read_609.py`.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node
from fleet_platform.models.process_stat import NodeProcessStat

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ps_read_node(db_session: AsyncSession):
    """Seed a node used for process-stats read tests."""
    node = Node(
        minion_id=f"ps-read-{uuid.uuid4()}",
        hostname="ps-read-host.local",
        node_token_hash=hash_password(secrets.token_urlsafe(16)),
        status="online",
        first_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node
    await db_session.delete(node)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ps_empty_node(db_session: AsyncSession):
    """A node with no process-stat rows at all."""
    node = Node(
        minion_id=f"ps-empty-{uuid.uuid4()}",
        hostname="ps-empty-host.local",
        node_token_hash=hash_password(secrets.token_urlsafe(16)),
        status="online",
        first_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node
    await db_session.delete(node)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_snapshots(db_session: AsyncSession, ps_read_node):
    """Insert two snapshots (older + newer) for ps_read_node.

    older_ts  — 5 minutes ago — 2 rows
    newer_ts  — now           — 3 rows (including highest mem/cpu)
    Returns (older_ts, newer_ts).
    """
    now = datetime.now(timezone.utc)
    older_ts = now - timedelta(minutes=5)
    newer_ts = now

    node_id = ps_read_node.id
    minion_id = ps_read_node.minion_id

    # --- older snapshot (should NOT appear in results) ---
    for i, (mem, cpu) in enumerate([(100_000, 5.0), (200_000, 10.0)]):
        row = NodeProcessStat(
            node_id=node_id,
            minion_id=minion_id,
            pid=1000 + i,
            name=f"old_proc_{i}",
            collected_at=older_ts,
            cpu_pct=cpu,
            mem_rss_bytes=mem,
        )
        db_session.add(row)

    # --- newer snapshot (should appear in results) ---
    # Rows: mem_rss_bytes 500k, 300k, 100k  /  cpu_pct 50.0, 20.0, 5.0
    for i, (mem, cpu) in enumerate([(500_000, 50.0), (300_000, 20.0), (100_000, 5.0)]):
        row = NodeProcessStat(
            node_id=node_id,
            minion_id=minion_id,
            pid=2000 + i,
            name=f"new_proc_{i}",
            collected_at=newer_ts,
            cpu_pct=cpu,
            mem_rss_bytes=mem,
        )
        db_session.add(row)

    await db_session.commit()
    return older_ts, newer_ts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_unknown_node_returns_404(client: AsyncClient, viewer_token: str):
    """GET /process_stats on an unknown UUID returns 404."""
    fake_id = uuid.uuid4()
    resp = await client.get(
        f"/api/v1/nodes/{fake_id}/process_stats",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Node not found"


async def test_no_telemetry_returns_empty(client: AsyncClient, viewer_token: str, ps_empty_node: Node):
    """GET /process_stats for a node with no rows returns 200 with empty processes."""
    resp = await client.get(
        f"/api/v1/nodes/{ps_empty_node.id}/process_stats",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_id"] == str(ps_empty_node.id)
    assert data["collected_at"] is None
    assert data["count"] == 0
    assert data["processes"] == []


async def test_returns_only_latest_snapshot(
    client: AsyncClient,
    viewer_token: str,
    ps_read_node: Node,
    seeded_snapshots,
):
    """Only rows from the most recent collected_at are returned."""
    _older_ts, newer_ts = seeded_snapshots
    resp = await client.get(
        f"/api/v1/nodes/{ps_read_node.id}/process_stats",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert data["node_id"] == str(ps_read_node.id)
    # All returned pids must come from the newer snapshot (2000+)
    pids = {p["pid"] for p in data["processes"]}
    assert pids == {2000, 2001, 2002}


async def test_sorted_by_mem_rss_bytes_desc(
    client: AsyncClient,
    viewer_token: str,
    ps_read_node: Node,
    seeded_snapshots,
):
    """Default sort is mem_rss_bytes DESC — first row has the highest value."""
    resp = await client.get(
        f"/api/v1/nodes/{ps_read_node.id}/process_stats?sort=mem_rss_bytes",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    procs = resp.json()["processes"]
    mem_values = [p["mem_rss_bytes"] for p in procs]
    assert mem_values == sorted(mem_values, reverse=True)
    assert mem_values[0] == 500_000


async def test_sorted_by_cpu_pct_desc(
    client: AsyncClient,
    viewer_token: str,
    ps_read_node: Node,
    seeded_snapshots,
):
    """sort=cpu_pct returns rows in descending CPU order."""
    resp = await client.get(
        f"/api/v1/nodes/{ps_read_node.id}/process_stats?sort=cpu_pct",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    procs = resp.json()["processes"]
    # cpu_pct comes back as string (Decimal serialisation); compare as float
    cpu_values = [float(p["cpu_pct"]) for p in procs]
    assert cpu_values == sorted(cpu_values, reverse=True)
    assert cpu_values[0] == pytest.approx(50.0)


async def test_limit_is_honoured(
    client: AsyncClient,
    viewer_token: str,
    ps_read_node: Node,
    seeded_snapshots,
):
    """limit=1 returns at most 1 process regardless of how many exist."""
    resp = await client.get(
        f"/api/v1/nodes/{ps_read_node.id}/process_stats?limit=1",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["processes"]) == 1
    assert data["count"] == 1


async def test_invalid_sort_param_rejected(
    client: AsyncClient,
    viewer_token: str,
    ps_read_node: Node,
):
    """sort=pid is not in the allow-list — FastAPI should return 422."""
    resp = await client.get(
        f"/api/v1/nodes/{ps_read_node.id}/process_stats?sort=pid",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 422


async def test_unauthenticated_returns_401(client: AsyncClient, ps_read_node: Node):
    """No auth header → 401."""
    resp = await client.get(f"/api/v1/nodes/{ps_read_node.id}/process_stats")
    assert resp.status_code == 401
