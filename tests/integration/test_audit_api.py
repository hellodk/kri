# tests/integration/test_audit_api.py
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.audit import AuditEvent


@pytest.fixture
async def audit_events(db_session: AsyncSession):
    events = [
        AuditEvent(
            event_at=datetime.now(UTC) - timedelta(hours=3),
            actor="alice@fleet.local",
            action="node.delete",
            resource_type="node",
        ),
        AuditEvent(
            event_at=datetime.now(UTC) - timedelta(hours=1),
            actor="bob@fleet.local",
            action="auth.login",
            resource_type=None,
        ),
        AuditEvent(
            event_at=datetime.now(UTC) - timedelta(minutes=10),
            actor="alice@fleet.local",
            action="settings.update",
            resource_type="setting",
        ),
    ]
    db_session.add_all(events)
    await db_session.commit()

    yield events

    for e in events:
        await db_session.delete(e)
    await db_session.commit()


async def test_audit_list_no_filters(admin_client: AsyncClient, audit_events):
    resp = await admin_client.get("/api/v1/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["total"] >= 3


async def test_audit_filter_by_actor(admin_client: AsyncClient, audit_events):
    resp = await admin_client.get("/api/v1/audit?actor=alice")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all("alice" in e["actor"] for e in items)


async def test_audit_filter_by_action(admin_client: AsyncClient, audit_events):
    resp = await admin_client.get("/api/v1/audit?action=auth.login")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all(e["action"] == "auth.login" for e in items)


async def test_audit_filter_by_resource_type(admin_client: AsyncClient, audit_events):
    resp = await admin_client.get("/api/v1/audit?resource_type=node")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all(e["resource_type"] == "node" for e in items)


async def test_audit_filter_from_ts(admin_client: AsyncClient, audit_events):
    from_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    resp = await admin_client.get(f"/api/v1/audit?from_ts={from_ts}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    # Should include the -1h and -10min events, not the -3h event
    assert len(items) >= 2
    # Verify none of the returned events pre-date from_ts
    for e in items:
        assert e["event_at"] >= from_ts[:19]  # rough ISO prefix check


async def test_audit_filter_to_ts(admin_client: AsyncClient, audit_events):
    to_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    resp = await admin_client.get(f"/api/v1/audit?to_ts={to_ts}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    # Should only include the -3h event among our seeded data
    alice_events = [e for e in items if e["actor"] == "alice@fleet.local"]
    assert all(e["action"] == "node.delete" for e in alice_events)


async def test_audit_filter_from_ts_and_to_ts(admin_client: AsyncClient, audit_events):
    from_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    to_ts = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    resp = await admin_client.get(f"/api/v1/audit?from_ts={from_ts}&to_ts={to_ts}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    # The -1h event should be in range; -10min and -3h should not
    assert len(items) >= 1
    assert all(e["event_at"] >= from_ts[:19] for e in items)


async def test_audit_pagination(admin_client: AsyncClient, audit_events):
    resp = await admin_client.get("/api/v1/audit?per_page=2&page=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) <= 2
    assert body["per_page"] == 2
    assert body["page"] == 1


async def test_audit_unauthorized(client: AsyncClient):
    resp = await client.get("/api/v1/audit")
    assert resp.status_code == 401
