"""Integration tests for playbook library API."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.playbook_catalog import PlaybookCatalog

# ── helpers ──────────────────────────────────────────────────────────────────


async def _make_catalog_entry(db: AsyncSession, *, enabled: bool = True) -> PlaybookCatalog:
    """Insert a catalog row and return it."""
    row = PlaybookCatalog(
        source_key="https://git.example.com/test-lib.git",
        source_label="test-lib",
        filename=f"test_play_{uuid.uuid4().hex[:8]}.yml",
        entry_type="playbook",
        enabled=enabled,
        enabled_by="admin@kri.local",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ── role enforcement ──────────────────────────────────────────────────────────


async def test_enable_requires_admin(operator_client: AsyncClient):
    """Operators cannot enable catalog entries."""
    r = await operator_client.post(
        "/api/v1/ansible/playbooks/library/enable",
        json={
            "source_key": "https://git.example.com/test-lib.git",
            "source_label": "test-lib",
            "filename": "denied.yml",
            "entry_type": "playbook",
        },
    )
    assert r.status_code == 403


async def test_disable_requires_admin(operator_client: AsyncClient, db_session: AsyncSession):
    """Operators cannot disable catalog entries."""
    row = await _make_catalog_entry(db_session)
    r = await operator_client.post(
        "/api/v1/ansible/playbooks/library/disable",
        json={"catalog_id": str(row.id)},
    )
    assert r.status_code == 403


async def test_enable_source_requires_admin(operator_client: AsyncClient):
    """Operators cannot bulk-enable a source."""
    r = await operator_client.post(
        "/api/v1/ansible/playbooks/library/enable-source",
        json={"source_key": "https://git.example.com/test-lib.git"},
    )
    assert r.status_code == 403


# ── enable / disable ──────────────────────────────────────────────────────────


async def test_enable_creates_catalog_row(admin_client: AsyncClient, db_session: AsyncSession):
    """POST /enable creates a new enabled catalog row."""
    filename = f"enable_test_{uuid.uuid4().hex[:8]}.yml"
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/enable",
        json={
            "source_key": "https://git.example.com/test-lib.git",
            "source_label": "test-lib",
            "filename": filename,
            "entry_type": "playbook",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True
    assert "id" in data

    result = await db_session.execute(select(PlaybookCatalog).where(PlaybookCatalog.filename == filename))
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.enabled is True


async def test_enable_is_idempotent(admin_client: AsyncClient, db_session: AsyncSession):
    """Enabling an already-enabled playbook succeeds and keeps it enabled."""
    row = await _make_catalog_entry(db_session)
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/enable",
        json={
            "source_key": row.source_key,
            "source_label": row.source_label,
            "filename": row.filename,
            "entry_type": row.entry_type,
        },
    )
    assert r.status_code == 200
    await db_session.refresh(row)
    assert row.enabled is True


async def test_disable_sets_enabled_false(admin_client: AsyncClient, db_session: AsyncSession):
    """POST /disable sets enabled=False on the catalog row."""
    row = await _make_catalog_entry(db_session)
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/disable",
        json={"catalog_id": str(row.id)},
    )
    assert r.status_code == 200
    await db_session.refresh(row)
    assert row.enabled is False


async def test_disable_nonexistent_returns_404(admin_client: AsyncClient):
    """POST /disable with unknown UUID returns 404."""
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/disable",
        json={"catalog_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


async def test_disable_response_shape(admin_client: AsyncClient, db_session: AsyncSession):
    """POST /disable returns id and enabled=False."""
    row = await _make_catalog_entry(db_session)
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/disable",
        json={"catalog_id": str(row.id)},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is False
    assert data["id"] == str(row.id)


# ── enable-source ─────────────────────────────────────────────────────────────


async def test_enable_source_returns_count(admin_client: AsyncClient):
    """POST /enable-source returns source_key and enabled_count."""
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/enable-source",
        json={"source_key": "https://git.example.com/nonexistent.git"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "source_key" in data
    assert "enabled_count" in data
    assert data["enabled_count"] == 0


# ── favorites ─────────────────────────────────────────────────────────────────


async def test_add_and_remove_favorite(operator_client: AsyncClient, db_session: AsyncSession):
    """POST then DELETE /favorites/{id} round-trip."""
    row = await _make_catalog_entry(db_session)

    add_r = await operator_client.post(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert add_r.status_code == 201

    del_r = await operator_client.delete(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert del_r.status_code == 200


async def test_add_favorite_nonexistent_returns_404(operator_client: AsyncClient):
    """Adding a favorite for an unknown catalog_id returns 404."""
    r = await operator_client.post(f"/api/v1/ansible/playbooks/library/favorites/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_add_favorite_is_idempotent(operator_client: AsyncClient, db_session: AsyncSession):
    """Adding the same favorite twice does not error."""
    row = await _make_catalog_entry(db_session)

    r1 = await operator_client.post(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert r1.status_code == 201

    r2 = await operator_client.post(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert r2.status_code == 201


async def test_remove_favorite_silent_if_not_exists(operator_client: AsyncClient, db_session: AsyncSession):
    """DELETE /favorites/{id} is silent when the favorite doesn't exist."""
    row = await _make_catalog_entry(db_session)
    r = await operator_client.delete(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert r.status_code == 200


async def test_favorite_response_shape(operator_client: AsyncClient, db_session: AsyncSession):
    """Favorites endpoints return catalog_id and favorited fields."""
    row = await _make_catalog_entry(db_session)

    add_r = await operator_client.post(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert add_r.status_code == 201
    add_data = add_r.json()
    assert add_data["catalog_id"] == str(row.id)
    assert add_data["favorited"] is True

    del_r = await operator_client.delete(f"/api/v1/ansible/playbooks/library/favorites/{row.id}")
    assert del_r.status_code == 200
    del_data = del_r.json()
    assert del_data["catalog_id"] == str(row.id)
    assert del_data["favorited"] is False


# ── audit events ──────────────────────────────────────────────────────────────


async def test_enable_creates_audit_event(admin_client: AsyncClient):
    """Enabling a playbook creates a playbook.enable audit event (verified via audit API)."""
    filename = f"audit_test_{uuid.uuid4().hex[:8]}.yml"
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/enable",
        json={
            "source_key": "https://git.example.com/test-lib.git",
            "source_label": "test-lib",
            "filename": filename,
            "entry_type": "playbook",
        },
    )
    assert r.status_code == 200

    audit_r = await admin_client.get("/api/v1/audit", params={"action": "playbook.enable"})
    assert audit_r.status_code == 200
    body = audit_r.json()
    assert body["total"] >= 1
    assert any(e["action"] == "playbook.enable" for e in body["items"])


async def test_disable_creates_audit_event(admin_client: AsyncClient, db_session: AsyncSession):
    """Disabling a playbook creates a playbook.disable audit event (verified via audit API)."""
    row = await _make_catalog_entry(db_session)
    r = await admin_client.post(
        "/api/v1/ansible/playbooks/library/disable",
        json={"catalog_id": str(row.id)},
    )
    assert r.status_code == 200

    audit_r = await admin_client.get("/api/v1/audit", params={"action": "playbook.disable"})
    assert audit_r.status_code == 200
    body = audit_r.json()
    assert body["total"] >= 1
    assert any(e["action"] == "playbook.disable" for e in body["items"])
