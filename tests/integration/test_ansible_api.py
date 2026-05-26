# tests/integration/test_ansible_api.py
from httpx import AsyncClient


async def test_get_settings_requires_admin(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/settings")
    assert r.status_code == 403


async def test_admin_can_set_and_get_settings(admin_client: AsyncClient):
    r = await admin_client.put("/api/v1/settings", json={
        "salt_master_address": "10.0.0.1",
        "ssh_bootstrap_username": "localadmin",
        "ssh_bootstrap_password": "secret123",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["salt_master_address"] == "10.0.0.1"
    assert data["ssh_bootstrap_username"] == "localadmin"
    assert data.get("ssh_bootstrap_password") is None


async def test_controller_pubkey_in_response(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/settings")
    assert r.status_code == 200
    assert "controller_pubkey" in r.json()


async def test_bootstrap_requires_operator(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/bootstrap", json={
        "minion_id": "test-node.local",
        "target_ip": "10.0.1.50",
    })
    assert r.status_code == 403
