"""Integration tests for POST /api/v1/settings/test-email (#417)."""

from httpx import AsyncClient


async def test_test_email_viewer_forbidden(viewer_client: AsyncClient):
    """Viewer role must receive 403 — endpoint is admin-only."""
    r = await viewer_client.post("/api/v1/settings/test-email", json={})
    assert r.status_code == 403


async def test_test_email_admin_no_smtp_host_returns_400(admin_client: AsyncClient):
    """Admin with no SMTP host configured must receive HTTP 400 with a clear message."""
    # Ensure smtp_host is absent / empty by not setting it
    r = await admin_client.post("/api/v1/settings/test-email", json={})
    # Could be 400 (no host) or 400 (SMTP refused) — in test DB smtp_host is blank by default
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body
    assert body["detail"]  # non-empty message
