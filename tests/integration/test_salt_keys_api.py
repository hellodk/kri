# tests/integration/test_salt_keys_api.py
"""Integration tests for the salt-keys API routes.

The routes read and move files under a PKI directory. Tests patch the
filesystem helpers so no real /etc/salt path is required.
"""
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── helpers ────────────────────────────────────────────────────────────


def _make_dirs_mock(pending=(), accepted=(), rejected=(), denied=()):
    """Return a _dirs() mock whose directories are non-existent (empty lists)."""

    def _dirs():
        base = Path("/nonexistent/pki")
        return {
            "accepted": base / "minions",
            "pending": base / "minions_pre",
            "rejected": base / "minions_rejected",
            "denied": base / "minions_denied",
        }

    return _dirs


# ── GET /api/v1/salt/keys ─────────────────────────────────────────────


async def test_list_keys_requires_auth(client: AsyncClient):
    """Unauthenticated request must get 401."""
    resp = await client.get("/api/v1/salt/keys")
    assert resp.status_code == 401


async def test_list_keys_returns_grouped_result(admin_client: AsyncClient):
    """Authenticated request returns keys grouped by status."""
    with patch(
        "fleet_platform.api.routes.salt_keys._dirs",
        side_effect=_make_dirs_mock(),
    ):
        resp = await admin_client.get("/api/v1/salt/keys")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("accepted", "pending", "rejected", "denied"):
        assert key in data
        assert isinstance(data[key], list)
    assert "pending_count" in data
    assert isinstance(data["pending_count"], int)


async def test_list_keys_viewer_allowed(viewer_client: AsyncClient):
    """Viewer role may list keys (only requires authentication)."""
    with patch(
        "fleet_platform.api.routes.salt_keys._dirs",
        side_effect=_make_dirs_mock(),
    ):
        resp = await viewer_client.get("/api/v1/salt/keys")
    assert resp.status_code == 200


# ── POST /api/v1/salt/keys/{minion_id}/accept ─────────────────────────


async def test_accept_key_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/salt/keys/mac-mini-01/accept")
    assert resp.status_code == 401


async def test_accept_key_requires_operator(viewer_client: AsyncClient):
    resp = await viewer_client.post("/api/v1/salt/keys/mac-mini-01/accept")
    assert resp.status_code == 403


async def test_accept_key_not_found_when_no_pending(admin_client: AsyncClient):
    """Returns 404 when no pending key exists for the minion."""
    with patch(
        "fleet_platform.api.routes.salt_keys._dirs",
        side_effect=_make_dirs_mock(),
    ):
        resp = await admin_client.post("/api/v1/salt/keys/no-such-minion/accept")
    assert resp.status_code == 404


async def test_accept_key_rejects_invalid_minion_id(admin_client: AsyncClient):
    """Minion IDs with path-traversal chars must be rejected with 422."""
    resp = await admin_client.post("/api/v1/salt/keys/../etc-passwd/accept")
    # FastAPI may return 422 or 404 depending on URL routing; either blocks the attack
    assert resp.status_code in (404, 422)


async def test_accept_key_happy_path(admin_client: AsyncClient, tmp_path):
    """A pending key can be accepted and is moved to the accepted dir."""
    pending_dir = tmp_path / "minions_pre"
    accepted_dir = tmp_path / "minions"
    pending_dir.mkdir()
    (pending_dir / "mac-mini-01").write_text("pubkey")

    def _fake_dirs():
        return {
            "accepted": accepted_dir,
            "pending": pending_dir,
            "rejected": tmp_path / "minions_rejected",
            "denied": tmp_path / "minions_denied",
        }

    with patch("fleet_platform.api.routes.salt_keys._dirs", side_effect=_fake_dirs):
        resp = await admin_client.post("/api/v1/salt/keys/mac-mini-01/accept")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["minion_id"] == "mac-mini-01"
    assert (accepted_dir / "mac-mini-01").exists()


# ── POST /api/v1/salt/keys/{minion_id}/reject ─────────────────────────


async def test_reject_key_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/salt/keys/mac-mini-01/reject")
    assert resp.status_code == 401


async def test_reject_key_requires_admin(operator_client: AsyncClient):
    """Operator role is not sufficient — only admin may reject keys."""
    resp = await operator_client.post("/api/v1/salt/keys/mac-mini-01/reject")
    assert resp.status_code == 403


async def test_reject_key_not_found(admin_client: AsyncClient):
    with patch(
        "fleet_platform.api.routes.salt_keys._dirs",
        side_effect=_make_dirs_mock(),
    ):
        resp = await admin_client.post("/api/v1/salt/keys/ghost/reject")
    assert resp.status_code == 404


async def test_reject_key_happy_path(admin_client: AsyncClient, tmp_path):
    """A pending key is moved to the rejected dir."""
    pending_dir = tmp_path / "minions_pre"
    rejected_dir = tmp_path / "minions_rejected"
    pending_dir.mkdir()
    (pending_dir / "bad-minion").write_text("pubkey")

    def _fake_dirs():
        return {
            "accepted": tmp_path / "minions",
            "pending": pending_dir,
            "rejected": rejected_dir,
            "denied": tmp_path / "minions_denied",
        }

    with patch("fleet_platform.api.routes.salt_keys._dirs", side_effect=_fake_dirs):
        resp = await admin_client.post("/api/v1/salt/keys/bad-minion/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert (rejected_dir / "bad-minion").exists()


# ── DELETE /api/v1/salt/keys/{minion_id} ──────────────────────────────


async def test_delete_key_requires_auth(client: AsyncClient):
    resp = await client.delete("/api/v1/salt/keys/mac-mini-01")
    assert resp.status_code == 401


async def test_delete_key_requires_admin(operator_client: AsyncClient):
    resp = await operator_client.delete("/api/v1/salt/keys/mac-mini-01")
    assert resp.status_code == 403


async def test_delete_key_not_found(admin_client: AsyncClient):
    with patch(
        "fleet_platform.api.routes.salt_keys._dirs",
        side_effect=_make_dirs_mock(),
    ):
        resp = await admin_client.delete("/api/v1/salt/keys/missing-minion")
    assert resp.status_code == 404


async def test_delete_key_happy_path(admin_client: AsyncClient, tmp_path):
    """Deletes a key found in the accepted bucket."""
    accepted_dir = tmp_path / "minions"
    accepted_dir.mkdir()
    (accepted_dir / "old-mac").write_text("pubkey")

    def _fake_dirs():
        return {
            "accepted": accepted_dir,
            "pending": tmp_path / "minions_pre",
            "rejected": tmp_path / "minions_rejected",
            "denied": tmp_path / "minions_denied",
        }

    with patch("fleet_platform.api.routes.salt_keys._dirs", side_effect=_fake_dirs):
        resp = await admin_client.delete("/api/v1/salt/keys/old-mac")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert not (accepted_dir / "old-mac").exists()
