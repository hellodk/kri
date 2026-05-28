# tests/integration/test_provisioning_api.py
"""Integration tests for the provisioning profiles API routes.

Endpoints under /api/v1/provisioning handle .mobileprovision file uploads,
listing, downloading, and deletion. Tests use an in-memory fake profile
to avoid needing real Apple-signed files.
"""
import io
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# Minimal .mobileprovision content — not a real CMS blob; parser gracefully
# returns {} when it can't find the plist, which is fine for these tests.
FAKE_PROVISION_CONTENT = b"fake-mobileprovision-content"
FAKE_PROVISION_FILENAME = "TestApp.mobileprovision"


# ── GET /api/v1/provisioning ──────────────────────────────────────────


async def test_list_profiles_requires_auth(client: AsyncClient):
    """Unauthenticated requests must get 401."""
    resp = await client.get("/api/v1/provisioning")
    assert resp.status_code == 401


async def test_list_profiles_viewer_allowed(viewer_client: AsyncClient):
    """Viewer may list profiles."""
    resp = await viewer_client.get("/api/v1/provisioning")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    assert "total" in data


async def test_list_profiles_returns_200(admin_client: AsyncClient):
    resp = await admin_client.get("/api/v1/provisioning")
    assert resp.status_code == 200


# ── POST /api/v1/provisioning ─────────────────────────────────────────


async def test_upload_profile_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/provisioning",
        files={"file": (FAKE_PROVISION_FILENAME, io.BytesIO(FAKE_PROVISION_CONTENT), "application/octet-stream")},
        data={"name": "TestApp"},
    )
    assert resp.status_code == 401


async def test_upload_profile_requires_operator(viewer_client: AsyncClient):
    """Viewer role must be rejected with 403."""
    resp = await viewer_client.post(
        "/api/v1/provisioning",
        files={"file": (FAKE_PROVISION_FILENAME, io.BytesIO(FAKE_PROVISION_CONTENT), "application/octet-stream")},
        data={"name": "TestApp"},
    )
    assert resp.status_code == 403


async def test_upload_profile_rejects_wrong_extension(admin_client: AsyncClient):
    """Non-.mobileprovision files must be rejected with 400."""
    resp = await admin_client.post(
        "/api/v1/provisioning",
        files={"file": ("bad-file.txt", io.BytesIO(b"not a profile"), "text/plain")},
        data={"name": "BadProfile"},
    )
    assert resp.status_code == 400


async def test_upload_profile_happy_path(admin_client: AsyncClient):
    """Valid upload returns 201 with the saved profile metadata."""
    resp = await admin_client.post(
        "/api/v1/provisioning",
        files={"file": (FAKE_PROVISION_FILENAME, io.BytesIO(FAKE_PROVISION_CONTENT), "application/octet-stream")},
        data={"name": "TestApp Profile", "description": "integration test profile"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["name"] == "TestApp Profile"
    assert data["filename"] == FAKE_PROVISION_FILENAME

    # Clean up
    profile_id = data["id"]
    await admin_client.delete(f"/api/v1/provisioning/{profile_id}")


# ── GET /api/v1/provisioning/{id}/download ────────────────────────────


async def test_download_profile_requires_auth(client: AsyncClient):
    resp = await client.get(f"/api/v1/provisioning/{uuid.uuid4()}/download")
    assert resp.status_code == 401


async def test_download_nonexistent_profile_returns_404(admin_client: AsyncClient):
    resp = await admin_client.get(f"/api/v1/provisioning/{uuid.uuid4()}/download")
    assert resp.status_code == 404


async def test_download_profile_happy_path(admin_client: AsyncClient):
    """Uploaded profile can be downloaded and content matches."""
    upload = await admin_client.post(
        "/api/v1/provisioning",
        files={"file": (FAKE_PROVISION_FILENAME, io.BytesIO(FAKE_PROVISION_CONTENT), "application/octet-stream")},
        data={"name": "Download Test Profile"},
    )
    assert upload.status_code == 201
    profile_id = upload.json()["id"]

    download = await admin_client.get(f"/api/v1/provisioning/{profile_id}/download")
    assert download.status_code == 200
    assert download.content == FAKE_PROVISION_CONTENT

    # Clean up
    await admin_client.delete(f"/api/v1/provisioning/{profile_id}")


# ── DELETE /api/v1/provisioning/{id} ─────────────────────────────────


async def test_delete_profile_requires_auth(client: AsyncClient):
    resp = await client.delete(f"/api/v1/provisioning/{uuid.uuid4()}")
    assert resp.status_code == 401


async def test_delete_profile_requires_operator(viewer_client: AsyncClient):
    resp = await viewer_client.delete(f"/api/v1/provisioning/{uuid.uuid4()}")
    assert resp.status_code == 403


async def test_delete_nonexistent_profile_returns_404(admin_client: AsyncClient):
    resp = await admin_client.delete(f"/api/v1/provisioning/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_profile_happy_path(admin_client: AsyncClient):
    """Create then delete a profile — second GET returns 404."""
    upload = await admin_client.post(
        "/api/v1/provisioning",
        files={"file": (FAKE_PROVISION_FILENAME, io.BytesIO(FAKE_PROVISION_CONTENT), "application/octet-stream")},
        data={"name": "Delete Me Profile"},
    )
    assert upload.status_code == 201
    profile_id = upload.json()["id"]

    del_resp = await admin_client.delete(f"/api/v1/provisioning/{profile_id}")
    assert del_resp.status_code == 204

    # Confirm gone
    dl = await admin_client.get(f"/api/v1/provisioning/{profile_id}/download")
    assert dl.status_code == 404
