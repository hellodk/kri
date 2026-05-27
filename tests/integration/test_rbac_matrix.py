"""Verify the RBAC permission matrix — every role/endpoint combination."""
# ── auditor fixtures ──────────────────────────────────────────────────────────
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fleet_platform.core.auth import create_access_token, hash_password
from fleet_platform.models.user import User


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def auditor_user(db_session):
    user = User(
        email="auditor-rbac@fleet.local",
        password_hash=hash_password("auditor123"),
        role="auditor",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def auditor_token(auditor_user: User) -> str:
    return create_access_token(
        user_id=str(auditor_user.id),
        email=auditor_user.email,
        role=auditor_user.role,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def auditor_client(app_with_test_db, auditor_token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {auditor_token}"},
    ) as ac:
        yield ac


# ── RBAC matrix tests ─────────────────────────────────────────────────────────

async def test_viewer_cannot_access_settings(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/settings")
    assert r.status_code == 403


async def test_operator_cannot_update_settings(operator_client: AsyncClient):
    r = await operator_client.put("/api/v1/settings", json={})
    assert r.status_code == 403


async def test_auditor_cannot_access_settings(auditor_client: AsyncClient):
    r = await auditor_client.get("/api/v1/settings")
    assert r.status_code == 403


async def test_admin_can_access_settings(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/settings")
    assert r.status_code == 200


async def test_viewer_can_list_nodes(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/nodes")
    assert r.status_code == 200


async def test_auditor_can_list_nodes(auditor_client: AsyncClient):
    r = await auditor_client.get("/api/v1/nodes")
    assert r.status_code == 200


async def test_viewer_cannot_bootstrap(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/bootstrap", json={
        "minion_id": "x", "target_ip": "1.2.3.4"
    })
    assert r.status_code == 403


async def test_auditor_cannot_bootstrap(auditor_client: AsyncClient):
    r = await auditor_client.post("/api/v1/ansible/bootstrap", json={
        "minion_id": "x", "target_ip": "1.2.3.4"
    })
    assert r.status_code == 403


async def test_viewer_cannot_run_playbook(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/playbooks/run", json={
        "playbook": "x.yml", "target_type": "node",
        "target_id": "00000000-0000-0000-0000-000000000001", "extravars": {}
    })
    assert r.status_code == 403


async def test_auditor_can_access_audit_log(auditor_client: AsyncClient):
    r = await auditor_client.get("/api/v1/audit")
    assert r.status_code == 200


async def test_viewer_cannot_access_audit_log(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/audit")
    assert r.status_code == 403


async def test_operator_cannot_access_audit_log(operator_client: AsyncClient):
    r = await operator_client.get("/api/v1/audit")
    assert r.status_code == 403


async def test_admin_can_access_audit_log(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/audit")
    assert r.status_code == 200


async def test_auditor_can_access_security_dashboard(auditor_client: AsyncClient):
    r = await auditor_client.get("/api/v1/security/dashboard")
    assert r.status_code == 200


async def test_viewer_cannot_access_security_dashboard(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/security/dashboard")
    assert r.status_code == 403


async def test_operator_can_access_security_dashboard(operator_client: AsyncClient):
    r = await operator_client.get("/api/v1/security/dashboard")
    assert r.status_code == 200
