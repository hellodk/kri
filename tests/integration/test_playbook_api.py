# tests/integration/test_playbook_api.py
from httpx import AsyncClient


async def test_list_playbooks_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/ansible/playbooks")
    assert r.status_code == 401


async def test_list_playbooks_viewer_can_access(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/ansible/playbooks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_list_playbooks_contains_bootstrap(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/ansible/playbooks")
    filenames = [p["filename"] for p in r.json()]
    assert "bootstrap_mac_mini.yml" in filenames


async def test_list_playbooks_includes_default_vars(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/ansible/playbooks")
    bootstrap = next((p for p in r.json() if p["filename"] == "bootstrap_mac_mini.yml"), None)
    assert bootstrap is not None
    assert "default_vars" in bootstrap
    assert isinstance(bootstrap["default_vars"], dict)


async def test_run_playbook_requires_operator(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/playbooks/run", json={
        "playbook": "bootstrap_mac_mini.yml",
        "target_type": "node",
        "target_id": "00000000-0000-0000-0000-000000000001",
        "extravars": {},
    })
    assert r.status_code == 403


async def test_run_playbook_rejects_path_traversal(operator_client: AsyncClient):
    r = await operator_client.post("/api/v1/ansible/playbooks/run", json={
        "playbook": "../../etc/passwd",
        "target_type": "node",
        "target_id": "00000000-0000-0000-0000-000000000001",
        "extravars": {},
    })
    assert r.status_code == 404


async def test_get_job_status_404_for_unknown(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/ansible/jobs/00000000-0000-0000-0000-000000000099")
    assert r.status_code == 404
