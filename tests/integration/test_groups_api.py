# tests/integration/test_groups_api.py
import uuid

from httpx import AsyncClient


async def test_create_static_group(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/groups",
        json={"name": "prod-servers", "type": "static"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "prod-servers"
    assert data["type"] == "static"
    assert "id" in data


async def test_create_dynamic_group(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/groups",
        json={
            "name": "prod-builders",
            "type": "dynamic",
            "predicate": {"and": [{"key": "env", "value": "prod"}, {"key": "role", "value": "builder"}]},
        },
    )
    assert response.status_code == 201
    assert response.json()["predicate"]["and"][0]["key"] == "env"


async def test_create_dynamic_group_missing_predicate_returns_422(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/groups",
        json={"name": "broken", "type": "dynamic"},
    )
    assert response.status_code == 422


async def test_list_groups(admin_client: AsyncClient):
    response = await admin_client.get("/api/v1/groups")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


async def test_get_group(admin_client: AsyncClient):
    create = await admin_client.post(
        "/api/v1/groups",
        json={"name": "test-get-group", "type": "static"},
    )
    group_id = create.json()["id"]
    response = await admin_client.get(f"/api/v1/groups/{group_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "test-get-group"


async def test_delete_group(admin_client: AsyncClient):
    create = await admin_client.post(
        "/api/v1/groups",
        json={"name": "to-delete", "type": "static"},
    )
    group_id = create.json()["id"]
    response = await admin_client.delete(f"/api/v1/groups/{group_id}")
    assert response.status_code == 204


async def test_get_deleted_group_returns_404(admin_client: AsyncClient):
    response = await admin_client.get(f"/api/v1/groups/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_create_group_requires_operator(viewer_client: AsyncClient):
    response = await viewer_client.post(
        "/api/v1/groups",
        json={"name": "viewer-group", "type": "static"},
    )
    assert response.status_code == 403


async def test_list_groups_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/groups")
    assert response.status_code == 401
