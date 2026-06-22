"""Integration tests for POST /api/v1/settings/test-email (#417)."""

from unittest.mock import patch

from httpx import AsyncClient


async def test_test_email_viewer_forbidden(viewer_client: AsyncClient):
    """Viewer role must receive 403 — endpoint is admin-only."""
    r = await viewer_client.post("/api/v1/settings/test-email", json={})
    assert r.status_code == 403


async def test_test_email_admin_no_smtp_host_returns_400(admin_client: AsyncClient):
    """Admin with no SMTP host configured must receive HTTP 400 with a clear message.

    The route reads SMTP settings via a synchronous session (``get_sync_db``)
    that is not part of the async test-DB override, so we mock the underlying
    send helper to exercise the route's ValueError -> HTTP 400 mapping.
    """
    with patch(
        "fleet_platform.services.digest_svc.send_test_email",
        side_effect=ValueError("SMTP host not configured"),
    ):
        r = await admin_client.post("/api/v1/settings/test-email", json={})
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body
    assert body["detail"]  # non-empty message
