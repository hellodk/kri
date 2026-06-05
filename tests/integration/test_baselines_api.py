# tests/integration/test_baselines_api.py
from httpx import AsyncClient

_SAMPLE_BASELINE = {
    "name": "test-global",
    "target_type": "global",
    "state_json": {
        "packages": {
            "required": [{"name": "git", "version": ">=2.39.0"}],
            "forbidden": [{"name": "teamviewer"}],
        }
    },
    "git_commit_sha": "abc1234",
}


async def test_create_baseline(admin_client: AsyncClient):
    response = await admin_client.post("/api/v1/baselines", json=_SAMPLE_BASELINE)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test-global"
    assert data["version"] == 1


async def test_list_baselines(admin_client: AsyncClient):
    await admin_client.post("/api/v1/baselines", json={**_SAMPLE_BASELINE, "name": "list-test"})
    response = await admin_client.get("/api/v1/baselines")
    assert response.status_code == 200
    assert "items" in response.json()


async def test_get_baseline(admin_client: AsyncClient):
    create = await admin_client.post("/api/v1/baselines", json={**_SAMPLE_BASELINE, "name": "get-test"})
    baseline_id = create.json()["id"]
    response = await admin_client.get(f"/api/v1/baselines/{baseline_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "get-test"


async def test_get_baseline_not_found(admin_client: AsyncClient):
    import uuid

    response = await admin_client.get(f"/api/v1/baselines/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_create_baseline_requires_admin(viewer_client: AsyncClient):
    response = await viewer_client.post("/api/v1/baselines", json=_SAMPLE_BASELINE)
    assert response.status_code == 403


async def test_list_baselines_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/baselines")
    assert response.status_code == 401
