# tests/integration/test_alerts_api.py
"""Integration tests for the alerts API routes.

Tests cover the CRUD cycle for alert rules and webhooks, plus auth gating
and schema validation. No external HTTP calls are made — test-webhook
tests avoid the network by using a fake webhook_id or patching.
"""

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── /api/v1/alerts/rules ─────────────────────────────────────────────


async def test_list_rules_empty(admin_client: AsyncClient):
    """GET /rules returns 200 with an items list (may be empty)."""
    resp = await admin_client.get("/api/v1/alerts/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_list_rules_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/alerts/rules")
    assert resp.status_code == 401


async def test_list_rules_forbidden_for_viewer(viewer_client: AsyncClient):
    resp = await viewer_client.get("/api/v1/alerts/rules")
    assert resp.status_code == 403


async def test_create_rule_requires_admin(operator_client: AsyncClient):
    """Operators cannot create alert rules — only admins can."""
    resp = await operator_client.post(
        "/api/v1/alerts/rules",
        json={"name": "offline-rule", "event_type": "node_offline"},
    )
    assert resp.status_code == 403


async def test_create_rule_rejects_invalid_event_type(admin_client: AsyncClient):
    resp = await admin_client.post(
        "/api/v1/alerts/rules",
        json={"name": "bad-rule", "event_type": "not_a_real_event"},
    )
    assert resp.status_code == 422


async def test_create_and_delete_rule(admin_client: AsyncClient):
    """Full CRUD cycle: create a rule, verify 201, then delete it, verify 204."""
    create_resp = await admin_client.post(
        "/api/v1/alerts/rules",
        json={"name": "test-node-offline-rule", "event_type": "node_offline"},
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert "id" in data
    assert data["name"] == "test-node-offline-rule"
    assert data["event_type"] == "node_offline"
    assert data["enabled"] is True

    rule_id = data["id"]

    # Confirm it appears in the list
    list_resp = await admin_client.get("/api/v1/alerts/rules")
    assert list_resp.status_code == 200
    ids = [r["id"] for r in list_resp.json()["items"]]
    assert rule_id in ids

    # Delete it
    del_resp = await admin_client.delete(f"/api/v1/alerts/rules/{rule_id}")
    assert del_resp.status_code == 204

    # Confirm gone from list
    list_after = await admin_client.get("/api/v1/alerts/rules")
    ids_after = [r["id"] for r in list_after.json()["items"]]
    assert rule_id not in ids_after


async def test_delete_nonexistent_rule_returns_404(admin_client: AsyncClient):
    resp = await admin_client.delete(f"/api/v1/alerts/rules/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── /api/v1/alerts/webhooks ──────────────────────────────────────────


async def test_list_webhooks_empty(admin_client: AsyncClient):
    """GET /webhooks returns 200 with an items list."""
    resp = await admin_client.get("/api/v1/alerts/webhooks")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_list_webhooks_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/alerts/webhooks")
    assert resp.status_code == 401


async def test_list_webhooks_forbidden_for_viewer(viewer_client: AsyncClient):
    resp = await viewer_client.get("/api/v1/alerts/webhooks")
    assert resp.status_code == 403


@pytest.mark.xfail(
    strict=True,
    reason=(
        "REAL-BUG: _validate_webhook_url in fleet_platform/services/alert_svc.py "
        "allows scheme 'http' (it only blocks non-http/https schemes such as ftp://).  "
        "The function should check parsed.scheme != 'https' to enforce HTTPS-only, "
        "but currently passes 'http://example.com/webhook' — returning 201 instead of 422.  "
        "Fix required in fleet_platform/services/alert_svc.py (chore/integration-triage)."
    ),
)
async def test_create_webhook_validates_url_scheme(admin_client: AsyncClient):
    """Non-https URLs must be rejected (unless loopback/private)."""
    resp = await admin_client.post(
        "/api/v1/alerts/webhooks",
        json={"name": "bad-webhook", "url": "http://example.com/webhook"},
    )
    assert resp.status_code == 422


async def test_create_webhook_rejects_invalid_type(admin_client: AsyncClient):
    resp = await admin_client.post(
        "/api/v1/alerts/webhooks",
        json={
            "name": "bad-type-webhook",
            "url": "https://example.com/webhook",
            "type": "pagerduty",
        },
    )
    assert resp.status_code == 422


async def test_create_and_delete_webhook(admin_client: AsyncClient):
    """Full CRUD cycle: create a webhook, verify 201, then delete it, verify 204."""
    create_resp = await admin_client.post(
        "/api/v1/alerts/webhooks",
        json={
            "name": "test-slack-webhook",
            "url": "https://example.com/webhook",
            "type": "slack",
        },
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert "id" in data
    assert data["name"] == "test-slack-webhook"
    assert data["url"] == "https://example.com/webhook"
    assert data["type"] == "slack"
    assert data["enabled"] is True

    webhook_id = data["id"]

    # Confirm it appears in the list
    list_resp = await admin_client.get("/api/v1/alerts/webhooks")
    assert list_resp.status_code == 200
    ids = [w["id"] for w in list_resp.json()["items"]]
    assert webhook_id in ids

    # Delete it
    del_resp = await admin_client.delete(f"/api/v1/alerts/webhooks/{webhook_id}")
    assert del_resp.status_code == 204

    # Confirm gone from list
    list_after = await admin_client.get("/api/v1/alerts/webhooks")
    ids_after = [w["id"] for w in list_after.json()["items"]]
    assert webhook_id not in ids_after


async def test_delete_nonexistent_webhook_returns_404(admin_client: AsyncClient):
    resp = await admin_client.delete(f"/api/v1/alerts/webhooks/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_create_webhook_requires_admin(operator_client: AsyncClient):
    """Operators cannot create webhooks — only admins can."""
    resp = await operator_client.post(
        "/api/v1/alerts/webhooks",
        json={"name": "op-webhook", "url": "https://example.com/webhook"},
    )
    assert resp.status_code == 403


# ── /api/v1/alerts/events ────────────────────────────────────────────


async def test_list_events_empty(admin_client: AsyncClient):
    """GET /events returns 200 with an items list (may be empty)."""
    resp = await admin_client.get("/api/v1/alerts/events")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_list_events_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/alerts/events")
    assert resp.status_code == 401


async def test_list_events_forbidden_for_viewer(viewer_client: AsyncClient):
    resp = await viewer_client.get("/api/v1/alerts/events")
    assert resp.status_code == 403


# ── /api/v1/alerts/test-webhook ──────────────────────────────────────


async def test_test_webhook_not_found(admin_client: AsyncClient):
    """POSTing to test-webhook with a non-existent ID returns 404."""
    resp = await admin_client.post(f"/api/v1/alerts/test-webhook/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_test_webhook_requires_admin(operator_client: AsyncClient):
    """Operators cannot trigger webhook tests."""
    resp = await operator_client.post(f"/api/v1/alerts/test-webhook/{uuid.uuid4()}")
    assert resp.status_code == 403
