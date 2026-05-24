# Fleet Platform Plan 5 — SBOM Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully implement the SBOM ingestion pipeline: CycloneDX parsing, component indexing, scan archival, and a read API for fleet-wide package inspection and search.

**Architecture:** The ingest endpoint (`POST /api/v1/ingest/sbom/{minion_id}`) already streams the uploaded CycloneDX JSON to a temp file and queues an `index_sbom` Celery task — both implemented in Plan 2 as stubs. This plan replaces those stubs with real implementations: a `SBOMParser` service that normalises CycloneDX JSON into `SBOMScan` + `SBOMComponent` rows, Celery tasks that bulk-insert components and archive old scans, and a read-only API for browsing and searching SBOM data. The `search_vector` tsvector GIN index (added in migration 001) is used for full-text package search.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0 async, psycopg3, Celery 5.4, Redis 7.4, PostgreSQL 17 + TimescaleDB. CycloneDX JSON (Syft output). pytest-asyncio for integration tests.

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `fleet_platform/schemas/sbom.py` | Pydantic response models for SBOM API |
| Create | `fleet_platform/services/sbom_parser.py` | CycloneDX JSON → SBOMScan + component dicts |
| Modify | `fleet_platform/workers/sbom_tasks.py` | Implement `index_sbom`; add `archive_old_scans`, `cleanup_old_sbom_scans` |
| Modify | `fleet_platform/workers/celery_app.py` | Add `archive-old-sbom-scans` beat entry |
| Create | `fleet_platform/api/routes/sbom.py` | GET routes: latest scan, scan list, components, search |
| Modify | `fleet_platform/api/main.py` | Register sbom router |
| Create | `salt/states/base/sbom_scan.sls` | Salt state: Syft execution + HTTP upload |
| Create | `tests/unit/test_sbom_parser.py` | Parser unit tests |
| Create | `tests/unit/test_sbom_tasks.py` | Task unit tests (mocked DB) |
| Create | `tests/integration/test_sbom_api.py` | SBOM API integration tests |

---

## Task 1: SBOM Schemas

**Files:**
- Create: `fleet_platform/schemas/sbom.py`

- [ ] **Step 1: Write the file**

```python
# fleet_platform/schemas/sbom.py
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SBOMScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    syft_version: str | None
    format: str
    scanned_at: datetime
    component_count: int | None


class SBOMComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_id: uuid.UUID
    node_id: uuid.UUID
    name: str
    version: str | None
    purl: str | None
    component_type: str | None
    licenses: list
    cpes: list


class SBOMSearchResult(BaseModel):
    name: str
    version: str | None
    purl: str | None
    component_type: str | None
    hostname: str
    node_id: uuid.UUID
    scan_id: uuid.UUID
    scanned_at: datetime
```

- [ ] **Step 2: Commit**

```bash
git checkout -b feat/plan-5-sbom-pipeline
git add fleet_platform/schemas/sbom.py
git commit -m "feat: SBOM response schemas (SBOMScanResponse, SBOMComponentResponse, SBOMSearchResult)"
```

---

## Task 2: SBOMParser Service + Unit Tests

**Files:**
- Create: `fleet_platform/services/sbom_parser.py`
- Create: `tests/unit/test_sbom_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sbom_parser.py
import uuid
from datetime import timezone

import pytest

from fleet_platform.services.sbom_parser import SBOMParser

_NODE_ID = str(uuid.uuid4())

_MINIMAL_CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.4",
    "metadata": {
        "timestamp": "2026-05-14T12:00:00Z",
        "tools": [{"name": "syft", "version": "1.2.3"}],
    },
    "components": [
        {
            "type": "library",
            "name": "openssl",
            "version": "3.0.2",
            "purl": "pkg:brew/openssl@3.0.2",
            "licenses": [{"expression": "OpenSSL"}],
            "cpe": "cpe:2.3:a:openssl:openssl:3.0.2:*:*:*:*:*:*:*",
        },
        {
            "type": "application",
            "name": "git",
            "version": "2.42.0",
            "purl": "pkg:brew/git@2.42.0",
            "licenses": [],
        },
    ],
}


def test_parse_returns_scan_and_components():
    parser = SBOMParser()
    scan, components = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    assert scan.node_id == uuid.UUID(_NODE_ID)
    assert scan.syft_version == "1.2.3"
    assert scan.format == "cyclonedx"
    assert scan.component_count == 2
    assert len(components) == 2


def test_parse_scanned_at_is_utc():
    parser = SBOMParser()
    scan, _ = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    assert scan.scanned_at.tzinfo == timezone.utc


def test_parse_component_fields():
    parser = SBOMParser()
    _, components = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    openssl = next(c for c in components if c["name"] == "openssl")
    assert openssl["version"] == "3.0.2"
    assert openssl["purl"] == "pkg:brew/openssl@3.0.2"
    assert openssl["component_type"] == "library"
    assert openssl["licenses"] == ["OpenSSL"]
    assert "cpe:2.3:a:openssl" in openssl["cpes"][0]


def test_parse_component_no_license():
    parser = SBOMParser()
    _, components = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    git = next(c for c in components if c["name"] == "git")
    assert git["licenses"] == []
    assert git["cpes"] == []


def test_parse_missing_tools_defaults_syft_version_to_none():
    doc = {**_MINIMAL_CYCLONEDX, "metadata": {"timestamp": "2026-05-14T12:00:00Z"}}
    parser = SBOMParser()
    scan, _ = parser.parse_cyclonedx(_NODE_ID, doc)
    assert scan.syft_version is None


def test_parse_empty_components():
    doc = {**_MINIMAL_CYCLONEDX, "components": []}
    parser = SBOMParser()
    scan, components = parser.parse_cyclonedx(_NODE_ID, doc)
    assert scan.component_count == 0
    assert components == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/unit/test_sbom_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'fleet_platform.services.sbom_parser'`

- [ ] **Step 3: Implement the parser**

```python
# fleet_platform/services/sbom_parser.py
import uuid
from datetime import datetime, timezone

from fleet_platform.models.sbom import SBOMScan


class SBOMParser:
    def parse_cyclonedx(self, node_id: str, raw: dict) -> tuple[SBOMScan, list[dict]]:
        metadata = raw.get("metadata", {})
        tools = metadata.get("tools", [])
        syft_version = next(
            (t.get("version") for t in tools if t.get("name") == "syft"), None
        )

        ts_raw = metadata.get("timestamp", "")
        try:
            scanned_at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            scanned_at = datetime.now(timezone.utc)

        raw_components = raw.get("components", [])
        components = [self._normalise(c) for c in raw_components]

        scan = SBOMScan(
            node_id=uuid.UUID(node_id),
            syft_version=syft_version,
            format="cyclonedx",
            scanned_at=scanned_at,
            component_count=len(components),
        )
        return scan, components

    def _normalise(self, comp: dict) -> dict:
        licenses = []
        for lic in comp.get("licenses", []):
            expr = lic.get("expression") or lic.get("id")
            if expr:
                licenses.append(expr)

        cpe = comp.get("cpe")
        cpes = [cpe] if cpe else []

        return {
            "name": comp.get("name", ""),
            "version": comp.get("version"),
            "purl": comp.get("purl"),
            "component_type": comp.get("type"),
            "licenses": licenses,
            "cpes": cpes,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/unit/test_sbom_parser.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/sbom_parser.py tests/unit/test_sbom_parser.py
git commit -m "feat: SBOMParser — CycloneDX JSON → SBOMScan + normalised component dicts"
```

---

## Task 3: Implement sbom_tasks (index_sbom + archive + cleanup) + Unit Tests

**Files:**
- Modify: `fleet_platform/workers/sbom_tasks.py`
- Create: `tests/unit/test_sbom_tasks.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sbom_tasks.py
import json
import os
import tempfile
import uuid
from unittest.mock import MagicMock, patch

import pytest

_NODE_ID = str(uuid.uuid4())

_CYCLONEDX_DOC = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.4",
    "metadata": {
        "timestamp": "2026-05-14T12:00:00Z",
        "tools": [{"name": "syft", "version": "1.2.3"}],
    },
    "components": [
        {"type": "library", "name": "openssl", "version": "3.0.2",
         "purl": "pkg:brew/openssl@3.0.2", "licenses": [], "cpe": None},
    ],
}


def _make_temp_file(content: dict) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(content, f)
        return f.name


def test_index_sbom_deletes_temp_file():
    path = _make_temp_file(_CYCLONEDX_DOC)
    assert os.path.exists(path)

    mock_scan = MagicMock()
    mock_scan.id = uuid.uuid4()

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.workers.sbom_tasks.get_sync_db", return_value=mock_db), \
         patch("fleet_platform.workers.sbom_tasks.SBOMParser") as MockParser, \
         patch("fleet_platform.workers.sbom_tasks.archive_old_scans") as mock_archive:
        MockParser.return_value.parse_cyclonedx.return_value = (mock_scan, [{"name": "openssl"}])
        from fleet_platform.workers.sbom_tasks import index_sbom
        result = index_sbom(_NODE_ID, path)

    assert not os.path.exists(path)
    assert result["status"] == "indexed"
    assert result["component_count"] == 1
    mock_archive.delay.assert_called_once_with(node_id=_NODE_ID, keep_count=3)


def test_index_sbom_missing_file_returns_error():
    with patch("fleet_platform.workers.sbom_tasks.get_sync_db"):
        from fleet_platform.workers.sbom_tasks import index_sbom
        result = index_sbom(_NODE_ID, "/tmp/nonexistent-sbom-file.json")
    assert result["status"] == "error"
    assert result["reason"] == "file_not_found"


def test_cleanup_old_sbom_scans_calls_db():
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.rowcount = 5

    with patch("fleet_platform.workers.sbom_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.sbom_tasks import cleanup_old_sbom_scans
        result = cleanup_old_sbom_scans(keep_count=3)

    assert result["deleted"] == 5
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/unit/test_sbom_tasks.py -v
```

Expected: test imports fail with `ImportError` (stub doesn't have `cleanup_old_sbom_scans`)

- [ ] **Step 3: Implement sbom_tasks.py**

```python
# fleet_platform/workers/sbom_tasks.py
import json
import os
import uuid as _uuid

from sqlalchemy import delete, select, text

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.sbom import SBOMComponent, SBOMScan
from fleet_platform.services.sbom_parser import SBOMParser
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.index_sbom",
    bind=True,
    max_retries=3,
    queue="sbom",
)
def index_sbom(self, node_id: str, file_path: str) -> dict:
    try:
        with open(file_path) as f:
            raw_json = json.load(f)
    except FileNotFoundError:
        return {"status": "error", "reason": "file_not_found"}
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass

    try:
        parser = SBOMParser()
        scan, components = parser.parse_cyclonedx(node_id, raw_json)

        with get_sync_db() as db:
            db.add(scan)
            db.flush()
            if components:
                db.bulk_insert_mappings(
                    SBOMComponent,
                    [{"scan_id": scan.id, "node_id": _uuid.UUID(node_id), **c} for c in components],
                )
            db.commit()

        archive_old_scans.delay(node_id=node_id, keep_count=3)
        return {"status": "indexed", "node_id": node_id, "component_count": len(components)}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.archive_old_scans",
    bind=True,
    max_retries=3,
    queue="sbom",
)
def archive_old_scans(self, node_id: str, keep_count: int = 3) -> dict:
    node_uuid = _uuid.UUID(node_id)
    try:
        with get_sync_db() as db:
            keep_ids = db.execute(
                select(SBOMScan.id)
                .where(SBOMScan.node_id == node_uuid)
                .order_by(SBOMScan.scanned_at.desc())
                .limit(keep_count)
            ).scalars().all()

            if not keep_ids:
                return {"deleted": 0}

            result = db.execute(
                delete(SBOMScan)
                .where(SBOMScan.node_id == node_uuid)
                .where(SBOMScan.id.not_in(keep_ids))
            )
            db.commit()
        return {"deleted": result.rowcount}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.cleanup_old_sbom_scans",
    queue="sbom",
)
def cleanup_old_sbom_scans(keep_count: int = 3) -> dict:
    """Delete old SBOM scans fleet-wide, keeping the last keep_count per node. Run via beat."""
    with get_sync_db() as db:
        result = db.execute(
            text("""
                DELETE FROM sbom_scans
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY node_id
                                   ORDER BY scanned_at DESC
                               ) AS rn
                        FROM sbom_scans
                    ) ranked
                    WHERE rn > :keep_count
                )
            """),
            {"keep_count": keep_count},
        )
        db.commit()
    return {"deleted": result.rowcount}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/unit/test_sbom_tasks.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/workers/sbom_tasks.py tests/unit/test_sbom_tasks.py
git commit -m "feat: implement index_sbom + archive_old_scans + cleanup_old_sbom_scans tasks"
```

---

## Task 4: Celery Beat Schedule

**Files:**
- Modify: `fleet_platform/workers/celery_app.py`

- [ ] **Step 1: Add the beat entry**

Replace the existing `beat_schedule` block in `fleet_platform/workers/celery_app.py`:

```python
from celery import Celery
from celery.schedules import crontab

from fleet_platform.core.config import settings

celery_app = Celery(
    "fleet_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "fleet_platform.workers.drift_tasks",
        "fleet_platform.workers.sbom_tasks",
        "fleet_platform.workers.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "fleet_platform.workers.drift_tasks.*": {"queue": "drift"},
        "fleet_platform.workers.sbom_tasks.*": {"queue": "sbom"},
        "fleet_platform.workers.maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "mark-stale-nodes": {
            "task": "fleet_platform.workers.maintenance.mark_stale_nodes",
            "schedule": 300,
        },
        "archive-old-sbom-scans": {
            "task": "fleet_platform.workers.sbom_tasks.cleanup_old_sbom_scans",
            "schedule": crontab(hour=2, minute=0),
            "kwargs": {"keep_count": 3},
        },
    },
)
```

- [ ] **Step 2: Verify the import works**

```bash
source .venv/bin/activate && python -c "from fleet_platform.workers.celery_app import celery_app; print('beat:', list(celery_app.conf.beat_schedule.keys()))"
```

Expected: `beat: ['mark-stale-nodes', 'archive-old-sbom-scans']`

- [ ] **Step 3: Commit**

```bash
git add fleet_platform/workers/celery_app.py
git commit -m "feat: add archive-old-sbom-scans Celery beat schedule (daily 2am UTC)"
```

---

## Task 5: SBOM API Routes + Integration Tests + Router Registration

**Files:**
- Create: `fleet_platform/api/routes/sbom.py`
- Modify: `fleet_platform/api/main.py`
- Create: `tests/integration/test_sbom_api.py`

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/integration/test_sbom_api.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/integration/test_sbom_api.py -v
```

Expected: `404 Not Found` on all routes (router not registered yet)

- [ ] **Step 3: Implement the SBOM router**

```python
# fleet_platform/api/routes/sbom.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Node
from fleet_platform.models.sbom import SBOMComponent, SBOMScan
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.sbom import (
    SBOMComponentResponse,
    SBOMScanResponse,
    SBOMSearchResult,
)

router = APIRouter(prefix="/api/v1/sbom")


@router.get("/search", response_model=list[SBOMSearchResult])
async def search_sbom(
    q: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    if len(q.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must be at least 3 characters",
        )

    latest_scan = (
        select(func.max(SBOMScan.scanned_at).label("max_at"), SBOMScan.node_id)
        .group_by(SBOMScan.node_id)
        .subquery()
    )

    result = await db.execute(
        select(SBOMComponent, SBOMScan, Node)
        .join(SBOMScan, SBOMComponent.scan_id == SBOMScan.id)
        .join(Node, SBOMComponent.node_id == Node.id)
        .join(
            latest_scan,
            and_(
                SBOMScan.node_id == latest_scan.c.node_id,
                SBOMScan.scanned_at == latest_scan.c.max_at,
            ),
        )
        .where(
            text("sbom_components.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q)
        )
        .order_by(SBOMComponent.name, Node.hostname)
        .limit(limit)
    )
    return [
        SBOMSearchResult(
            name=comp.name,
            version=comp.version,
            purl=comp.purl,
            component_type=comp.component_type,
            hostname=node.hostname,
            node_id=node.id,
            scan_id=scan.id,
            scanned_at=scan.scanned_at,
        )
        for comp, scan, node in result.all()
    ]


@router.get("/{node_id}/latest", response_model=SBOMScanResponse)
async def get_latest_scan(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(SBOMScan)
        .where(SBOMScan.node_id == node_id)
        .order_by(SBOMScan.scanned_at.desc())
        .limit(1)
    )
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No scans found for node")
    return SBOMScanResponse.model_validate(scan)


@router.get("/{node_id}/scans", response_model=PaginatedResponse[SBOMScanResponse])
async def list_scans(
    node_id: uuid.UUID,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (
        await db.execute(
            select(func.count()).select_from(SBOMScan).where(SBOMScan.node_id == node_id)
        )
    ).scalar_one()
    result = await db.execute(
        select(SBOMScan)
        .where(SBOMScan.node_id == node_id)
        .order_by(SBOMScan.scanned_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    scans = result.scalars().all()
    return PaginatedResponse(
        items=[SBOMScanResponse.model_validate(s) for s in scans],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{node_id}/scans/{scan_id}/components", response_model=PaginatedResponse[SBOMComponentResponse])
async def list_scan_components(
    node_id: uuid.UUID,
    scan_id: uuid.UUID,
    page: int = 1,
    per_page: int = 100,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (
        await db.execute(
            select(func.count())
            .select_from(SBOMComponent)
            .where(SBOMComponent.scan_id == scan_id)
            .where(SBOMComponent.node_id == node_id)
        )
    ).scalar_one()
    result = await db.execute(
        select(SBOMComponent)
        .where(SBOMComponent.scan_id == scan_id)
        .where(SBOMComponent.node_id == node_id)
        .order_by(SBOMComponent.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    components = result.scalars().all()
    return PaginatedResponse(
        items=[SBOMComponentResponse.model_validate(c) for c in components],
        total=total,
        page=page,
        per_page=per_page,
    )
```

- [ ] **Step 4: Register the router in main.py**

In `fleet_platform/api/main.py`, update the imports and `include_router` calls:

```python
from fleet_platform.api.routes import (
    health, auth, nodes, ingest, fleet, groups, search, baselines, drift, executions, sbom
)
```

And add inside `create_app()` after the existing routers:

```python
    app.include_router(sbom.router, tags=["sbom"])
```

- [ ] **Step 5: Run the integration tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_sbom_api.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: `150 passed` (143 existing + 7 new)

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/api/routes/sbom.py fleet_platform/api/main.py tests/integration/test_sbom_api.py
git commit -m "feat: SBOM API — latest scan, scan list, components, full-text search"
```

---

## Task 6: Salt State + Smoke Test

**Files:**
- Create: `salt/states/base/sbom_scan.sls`

- [ ] **Step 1: Write the Salt state**

```yaml
# salt/states/base/sbom_scan.sls
# Runs Syft on the node and uploads the CycloneDX JSON to the platform.
# Requires: syft installed at /usr/local/bin/syft, fleet_platform pillar configured.
#
# Usage: salt '*' state.apply base.sbom_scan

sbom_scan_run:
  cmd.run:
    - name: |
        /usr/local/bin/syft packages \
          --scope all-layers \
          --output cyclonedx-json \
          / > /tmp/sbom-{{ grains['id'] }}-$(date +%Y%m%d%H%M%S).json
    - timeout: 300
    - creates: /tmp/sbom-{{ grains['id'] }}-*.json

sbom_upload:
  module.run:
    - name: http.query
    - url: {{ pillar['fleet_platform']['ingest_url'] }}/api/v1/ingest/sbom/{{ grains['id'] }}
    - method: POST
    - header_list:
        - "X-Node-Token: {{ pillar['fleet_platform']['node_token'] }}"
        - "Content-Type: application/json"
    - data: __slot__:salt:file.read(/tmp/sbom-{{ grains['id'] }}-*.json)
    - require:
        - cmd: sbom_scan_run

sbom_cleanup:
  file.absent:
    - name: /tmp/sbom-{{ grains['id'] }}-*.json
    - require:
        - module: sbom_upload
```

- [ ] **Step 2: Verify the file is in place**

```bash
cat salt/states/base/sbom_scan.sls
```

Expected: prints the YAML above without error.

- [ ] **Step 3: Run the full test suite one final time**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: `150 passed` (or more if any fixture counts differ slightly)

- [ ] **Step 4: Commit and verify git log**

```bash
git add salt/states/base/sbom_scan.sls
git commit -m "feat: Salt state for Syft SBOM scan + upload (sbom_scan.sls)"
git log --oneline -8
```

Expected output (most recent first):
```
<sha>  feat: Salt state for Syft SBOM scan + upload (sbom_scan.sls)
<sha>  feat: SBOM API — latest scan, scan list, components, full-text search
<sha>  feat: add archive-old-sbom-scans Celery beat schedule (daily 2am UTC)
<sha>  feat: implement index_sbom + archive_old_scans + cleanup_old_sbom_scans tasks
<sha>  feat: SBOMParser — CycloneDX JSON → SBOMScan + normalised component dicts
<sha>  feat: SBOM response schemas (SBOMScanResponse, SBOMComponentResponse, SBOMSearchResult)
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] CycloneDX JSON parsing → Task 2 (SBOMParser)
- [x] index_sbom Celery task (replaces Plan 2 stub) → Task 3
- [x] archive_old_scans per-node after each ingest → Task 3
- [x] cleanup_old_sbom_scans fleet-wide beat task → Tasks 3+4
- [x] GET /api/v1/sbom/{node_id}/latest → Task 5
- [x] GET /api/v1/sbom/{node_id}/scans → Task 5
- [x] GET /api/v1/sbom/{node_id}/scans/{scan_id}/components → Task 5
- [x] GET /api/v1/sbom/search (full-text via tsvector GIN index) → Task 5
- [x] Salt state for Syft scan + upload → Task 6
- [x] All routes require JWT auth → Task 5 (get_current_user on every route)
- [x] Temp file deleted even on parse error (finally block) → Task 3

**Type consistency:**
- `SBOMParser.parse_cyclonedx(node_id: str, raw: dict) -> tuple[SBOMScan, list[dict]]` — used consistently in Tasks 2, 3
- `index_sbom(self, node_id: str, file_path: str)` — matches Plan 2 stub signature
- `archive_old_scans(self, node_id: str, keep_count: int = 3)` — matches call in index_sbom: `archive_old_scans.delay(node_id=node_id, keep_count=3)`
- `SBOMScanResponse`, `SBOMComponentResponse`, `SBOMSearchResult` — defined Task 1, used Task 5
