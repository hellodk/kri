import secrets
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node
from fleet_platform.models.sbom import SBOMComponent, SBOMScan


@pytest.fixture
async def node_with_sbom(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="sbom-test-01.local",
        hostname="sbom-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    scan = SBOMScan(
        node_id=node.id,
        syft_version="1.2.3",
        format="cyclonedx",
        scanned_at=datetime.now(UTC),
        component_count=2,
    )
    db_session.add(scan)
    await db_session.commit()
    await db_session.refresh(scan)

    comp1 = SBOMComponent(
        scan_id=scan.id,
        node_id=node.id,
        name="openssl",
        version="3.0.2",
        purl="pkg:brew/openssl@3.0.2",
        component_type="library",
        licenses=["OpenSSL"],
        cpes=["cpe:2.3:a:openssl:openssl:3.0.2:*:*:*:*:*:*:*"],
    )
    comp2 = SBOMComponent(
        scan_id=scan.id,
        node_id=node.id,
        name="git",
        version="2.42.0",
        purl="pkg:brew/git@2.42.0",
        component_type="application",
        licenses=[],
        cpes=[],
    )
    db_session.add_all([comp1, comp2])
    await db_session.commit()

    yield node, scan, [comp1, comp2]

    await db_session.delete(comp1)
    await db_session.delete(comp2)
    await db_session.delete(scan)
    await db_session.delete(node)
    await db_session.commit()


async def test_get_latest_scan(admin_client: AsyncClient, node_with_sbom):
    node, scan, _ = node_with_sbom
    response = await admin_client.get(f"/api/v1/sbom/{node.id}/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(scan.id)
    assert data["syft_version"] == "1.2.3"
    assert data["component_count"] == 2


async def test_get_latest_scan_not_found(admin_client: AsyncClient):
    response = await admin_client.get(f"/api/v1/sbom/{uuid.uuid4()}/latest")
    assert response.status_code == 404


async def test_list_scans(admin_client: AsyncClient, node_with_sbom):
    node, _, _ = node_with_sbom
    response = await admin_client.get(f"/api/v1/sbom/{node.id}/scans")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


async def test_list_scan_components(admin_client: AsyncClient, node_with_sbom):
    node, scan, _ = node_with_sbom
    response = await admin_client.get(f"/api/v1/sbom/{node.id}/scans/{scan.id}/components")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    names = {c["name"] for c in data["items"]}
    assert names == {"openssl", "git"}


async def test_search_sbom(admin_client: AsyncClient, node_with_sbom):
    response = await admin_client.get("/api/v1/sbom/search?q=openssl")
    assert response.status_code == 200
    results = response.json()
    assert any(r["name"] == "openssl" for r in results)


async def test_search_requires_3_chars(admin_client: AsyncClient):
    response = await admin_client.get("/api/v1/sbom/search?q=op")
    assert response.status_code == 422


async def test_sbom_requires_auth(client: AsyncClient, node_with_sbom):
    node, _, _ = node_with_sbom
    response = await client.get(f"/api/v1/sbom/{node.id}/latest")
    assert response.status_code == 401
