# Email Digest + Jenkins Build Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a weekly HTML email digest showing fleet health and Jenkins build statistics, with Jenkins pushing build results to kri via a webhook endpoint after each job completes.

**Architecture:** Jenkins calls `POST /api/v1/builds/ingest` (authenticated via `X-Jenkins-Secret` shared secret) after every build, kri persists results in a `jenkins_build_events` table, and a Celery beat task fires every Monday at 08:00 UTC to assemble an HTML email and send it over SMTP. SMTP credentials and the Jenkins secret are stored as encrypted platform settings. An admin can also trigger the digest on-demand via `POST /api/v1/digest/send-now`.

**Tech Stack:** FastAPI, SQLAlchemy (async for routes, sync for Celery), Alembic, Celery beat, Python `smtplib`, Pydantic v2, React/TypeScript frontend.

---

## File Map

**Create:**
- `fleet_platform/models/jenkins_build_event.py` — JenkinsBuildEvent ORM model
- `fleet_platform/db/migrations/versions/021_jenkins_build_events.py` — Alembic migration
- `fleet_platform/schemas/builds.py` — JenkinsBuildIngestPayload + JenkinsBuildResponse Pydantic schemas
- `fleet_platform/api/routes/builds.py` — POST /api/v1/builds/ingest, GET /api/v1/builds/recent, POST /api/v1/digest/send-now
- `fleet_platform/services/digest_svc.py` — HTML email renderer + SMTP sender (sync, for Celery)
- `fleet_platform/workers/digest_tasks.py` — Celery beat task `weekly_digest`
- `frontend/src/api/builds.ts` — TypeScript API client for builds + digest
- `tests/unit/test_digest_svc.py` — unit tests for digest service
- `tests/integration/test_builds_ingest.py` — integration tests for the ingest endpoint

**Modify:**
- `fleet_platform/services/platform_settings_svc.py` — add SMTP/Jenkins constants + `get_setting_sync()`
- `fleet_platform/schemas/ansible.py` — add SMTP + Jenkins fields to PlatformSettingsUpdate/Response
- `fleet_platform/api/routes/platform_settings.py` — handle the new settings fields
- `fleet_platform/workers/celery_app.py` — include digest_tasks, add beat schedule entry
- `fleet_platform/api/main.py` — register builds router
- `frontend/src/api/ansible.ts` — add new settings fields to PlatformSettings interface
- `frontend/src/pages/SettingsPage.tsx` — new "Notifications" tab

---

## Task 1: JenkinsBuildEvent model + migration 021

**Files:**
- Create: `fleet_platform/models/jenkins_build_event.py`
- Create: `fleet_platform/db/migrations/versions/021_jenkins_build_events.py`
- Test: `tests/unit/test_digest_svc.py` (empty placeholder so pytest doesn't fail)

- [ ] **Step 1: Write a minimal failing test that imports the model**

```python
# tests/unit/test_digest_svc.py
import pytest


def test_placeholder():
    """Placeholder — will be filled in T4."""
    pass
```

- [ ] **Step 2: Run it to confirm it passes (no-fail baseline)**

```bash
source .venv/bin/activate && pytest tests/unit/test_digest_svc.py -v
```

Expected: 1 PASSED

- [ ] **Step 3: Create the JenkinsBuildEvent model**

```python
# fleet_platform/models/jenkins_build_event.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class JenkinsBuildEvent(Base):
    __tablename__ = "jenkins_build_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    def __init__(self, **kw: object) -> None:
        if "id" not in kw:
            kw["id"] = uuid.uuid4()
        super().__init__(**kw)

    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    build_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # SUCCESS, FAILURE, UNSTABLE, ABORTED
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    test_pass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_fail: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_name", "build_number", name="uq_jenkins_build_job_number"),
        Index("idx_jenkins_build_started_at", "started_at"),
        Index("idx_jenkins_build_result", "result"),
    )
```

- [ ] **Step 4: Create migration 021**

```python
# fleet_platform/db/migrations/versions/021_jenkins_build_events.py
"""add jenkins_build_events table

Revision ID: 021
Revises: 020
Create Date: 2026-05-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jenkins_build_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_name", sa.String(255), nullable=False),
        sa.Column("build_number", sa.Integer, nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("test_pass", sa.Integer, nullable=True),
        sa.Column("test_fail", sa.Integer, nullable=True),
        sa.Column("test_total", sa.Integer, nullable=True),
        sa.Column("node_name", sa.String(255), nullable=True),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.UniqueConstraint("job_name", "build_number", name="uq_jenkins_build_job_number"),
    )
    op.create_index("idx_jenkins_build_started_at", "jenkins_build_events", ["started_at"])
    op.create_index("idx_jenkins_build_result", "jenkins_build_events", ["result"])


def downgrade() -> None:
    op.drop_index("idx_jenkins_build_result")
    op.drop_index("idx_jenkins_build_started_at")
    op.drop_table("jenkins_build_events")
```

**Note:** Migration 021 depends on 020 (from Plan 13). If Plan 13 has not been merged yet, temporarily set `down_revision = "019"` and `revision = "020"` instead — but coordinate with the Plan 13 branch to avoid revision conflicts before merging.

- [ ] **Step 5: Run the migration on the dev DB**

```bash
source .venv/bin/activate && alembic upgrade 021
```

Expected: `Running upgrade 020 -> 021, add jenkins_build_events table`

- [ ] **Step 6: Confirm table exists**

```bash
source .venv/bin/activate && python -c "
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
with get_sync_db() as db:
    count = db.query(JenkinsBuildEvent).count()
    print(f'jenkins_build_events rows: {count}')
"
```

Expected: `jenkins_build_events rows: 0`

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/models/jenkins_build_event.py \
        fleet_platform/db/migrations/versions/021_jenkins_build_events.py \
        tests/unit/test_digest_svc.py
git commit -m "feat: add JenkinsBuildEvent model and migration 021"
```

---

## Task 2: Jenkins builds ingest endpoint

Jenkins calls this endpoint after every build. Auth uses a shared secret in `X-Jenkins-Secret` header — no API tokens.

**Files:**
- Create: `fleet_platform/schemas/builds.py`
- Create: `fleet_platform/api/routes/builds.py`
- Modify: `fleet_platform/api/main.py` — register builds router
- Test: `tests/integration/test_builds_ingest.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_builds_ingest.py
import pytest
from datetime import UTC, datetime
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_ingest_build_requires_secret(async_client: AsyncClient):
    payload = {
        "job_name": "my-pipeline",
        "build_number": 1,
        "result": "SUCCESS",
        "started_at": datetime.now(UTC).isoformat(),
    }
    resp = await async_client.post("/api/v1/builds/ingest", json=payload)
    assert resp.status_code == 401


async def test_ingest_build_wrong_secret(async_client: AsyncClient, db_session):
    from fleet_platform.models.platform_setting import PlatformSetting
    db_session.add(PlatformSetting(
        key="jenkins_ingest_secret", value="correct-secret", is_encrypted=False
    ))
    await db_session.commit()

    payload = {
        "job_name": "my-pipeline",
        "build_number": 1,
        "result": "SUCCESS",
        "started_at": datetime.now(UTC).isoformat(),
    }
    resp = await async_client.post(
        "/api/v1/builds/ingest",
        json=payload,
        headers={"X-Jenkins-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401


async def test_ingest_build_success(async_client: AsyncClient, db_session):
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
    from sqlalchemy import select

    secret = "test-secret-abc123"
    db_session.add(PlatformSetting(
        key="jenkins_ingest_secret", value=secret, is_encrypted=False
    ))
    await db_session.commit()

    payload = {
        "job_name": "deploy-prod",
        "build_number": 42,
        "result": "SUCCESS",
        "duration_ms": 12300,
        "started_at": datetime.now(UTC).isoformat(),
        "test_pass": 97,
        "test_fail": 3,
        "test_total": 100,
        "node_name": "mac-mini-1",
        "branch": "main",
    }
    resp = await async_client.post(
        "/api/v1/builds/ingest",
        json=payload,
        headers={"X-Jenkins-Secret": secret},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    result = await db_session.execute(
        select(JenkinsBuildEvent).where(
            JenkinsBuildEvent.job_name == "deploy-prod",
            JenkinsBuildEvent.build_number == 42,
        )
    )
    event = result.scalar_one()
    assert event.result == "SUCCESS"
    assert event.test_pass == 97


async def test_ingest_build_idempotent(async_client: AsyncClient, db_session):
    """Duplicate ingest with same job_name + build_number returns 200 without error."""
    from fleet_platform.models.platform_setting import PlatformSetting

    secret = "idempotent-secret"
    db_session.add(PlatformSetting(
        key="jenkins_ingest_secret", value=secret, is_encrypted=False
    ))
    await db_session.commit()

    payload = {
        "job_name": "ci-test",
        "build_number": 1,
        "result": "FAILURE",
        "started_at": datetime.now(UTC).isoformat(),
    }
    headers = {"X-Jenkins-Secret": secret}
    resp1 = await async_client.post("/api/v1/builds/ingest", json=payload, headers=headers)
    resp2 = await async_client.post("/api/v1/builds/ingest", json=payload, headers=headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ok"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/integration/test_builds_ingest.py -v
```

Expected: ImportError or 404 (route not registered yet)

- [ ] **Step 3: Create the Pydantic schemas**

```python
# fleet_platform/schemas/builds.py
from datetime import datetime

from pydantic import BaseModel, field_validator


class JenkinsBuildIngestPayload(BaseModel):
    job_name: str
    build_number: int
    result: str  # SUCCESS, FAILURE, UNSTABLE, ABORTED, NOT_BUILT
    duration_ms: int | None = None
    started_at: datetime
    test_pass: int | None = None
    test_fail: int | None = None
    test_total: int | None = None
    node_name: str | None = None
    branch: str | None = None

    @field_validator("result")
    @classmethod
    def validate_result(cls, v: str) -> str:
        allowed = {"SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT"}
        if v not in allowed:
            raise ValueError(f"result must be one of {allowed}")
        return v

    @field_validator("job_name")
    @classmethod
    def validate_job_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("job_name cannot be empty")
        return v.strip()


class JenkinsBuildResponse(BaseModel):
    id: str
    job_name: str
    build_number: int
    result: str
    duration_ms: int | None
    started_at: datetime
    test_pass: int | None
    test_fail: int | None
    test_total: int | None
    node_name: str | None
    branch: str | None
```

- [ ] **Step 4: Create the builds router**

```python
# fleet_platform/api/routes/builds.py
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
from fleet_platform.schemas.builds import JenkinsBuildIngestPayload, JenkinsBuildResponse
from fleet_platform.services.platform_settings_svc import JENKINS_INGEST_SECRET, get_setting

router = APIRouter(prefix="/api/v1/builds")


async def _verify_jenkins_secret(
    x_jenkins_secret: str | None,
    db: AsyncSession,
) -> None:
    """Raise 401 if header is missing or does not match the stored secret."""
    if not x_jenkins_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Jenkins-Secret")
    expected = await get_setting(db, JENKINS_INGEST_SECRET)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jenkins ingest secret not configured — set it in Settings",
        )
    if not hmac.compare_digest(x_jenkins_secret, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-Jenkins-Secret")


@router.post("/ingest")
async def ingest_build(
    payload: JenkinsBuildIngestPayload,
    x_jenkins_secret: str | None = Header(alias="X-Jenkins-Secret", default=None),
    db: AsyncSession = Depends(get_db),
):
    """Jenkins calls this after every build. Idempotent: duplicate (job_name, build_number) is a no-op."""
    await _verify_jenkins_secret(x_jenkins_secret, db)

    # Check idempotency: skip if already ingested
    existing = await db.execute(
        select(JenkinsBuildEvent).where(
            JenkinsBuildEvent.job_name == payload.job_name,
            JenkinsBuildEvent.build_number == payload.build_number,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {"status": "ok", "detail": "already ingested"}

    event = JenkinsBuildEvent(
        job_name=payload.job_name,
        build_number=payload.build_number,
        result=payload.result,
        duration_ms=payload.duration_ms,
        started_at=payload.started_at,
        test_pass=payload.test_pass,
        test_fail=payload.test_fail,
        test_total=payload.test_total,
        node_name=payload.node_name,
        branch=payload.branch,
    )
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"status": "ok", "detail": "already ingested"}

    return {"status": "ok", "id": str(event.id)}


@router.get("/recent", response_model=list[JenkinsBuildResponse])
async def list_recent_builds(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer")),
):
    """Return the most recent Jenkins build events (newest first)."""
    result = await db.execute(
        select(JenkinsBuildEvent)
        .order_by(JenkinsBuildEvent.started_at.desc())
        .limit(min(limit, 200))
    )
    builds = result.scalars().all()
    return [
        JenkinsBuildResponse(
            id=str(b.id),
            job_name=b.job_name,
            build_number=b.build_number,
            result=b.result,
            duration_ms=b.duration_ms,
            started_at=b.started_at,
            test_pass=b.test_pass,
            test_fail=b.test_fail,
            test_total=b.test_total,
            node_name=b.node_name,
            branch=b.branch,
        )
        for b in builds
    ]
```

- [ ] **Step 5: Register the builds router in main.py**

In `fleet_platform/api/main.py`, add the import and `app.include_router` call.

After the existing `from fleet_platform.api.routes.fleet_health import router as fleet_health_router` import block, add:

```python
from fleet_platform.api.routes.builds import router as builds_router
```

Then after `app.include_router(fleet_health.router, tags=["fleet-health"])`, add:

```python
app.include_router(builds_router, tags=["builds"])
```

- [ ] **Step 6: Run the integration tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_builds_ingest.py -v
```

Expected: 4 PASSED

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/schemas/builds.py \
        fleet_platform/api/routes/builds.py \
        fleet_platform/api/main.py
git commit -m "feat: add Jenkins build ingest endpoint POST /api/v1/builds/ingest"
```

---

## Task 3: SMTP + Jenkins settings — constants, schemas, API routes, frontend types

**Files:**
- Modify: `fleet_platform/services/platform_settings_svc.py`
- Modify: `fleet_platform/schemas/ansible.py`
- Modify: `fleet_platform/api/routes/platform_settings.py`
- Modify: `frontend/src/api/ansible.ts`

- [ ] **Step 1: Add constants and `get_setting_sync` to platform_settings_svc.py**

Add the following constants after the existing `VNC_ENABLED` constant:

```python
# Email digest + Jenkins settings
SMTP_HOST = "smtp_host"
SMTP_PORT = "smtp_port"
SMTP_USERNAME = "smtp_username"
SMTP_PASSWORD = "smtp_password"
SMTP_FROM = "smtp_from"
DIGEST_RECIPIENTS = "digest_recipients"  # comma-separated email list
JENKINS_INGEST_SECRET = "jenkins_ingest_secret"
```

Add `get_setting_sync` after the existing `get_setting` function (for Celery workers that use sync SQLAlchemy sessions):

```python
def get_setting_sync(db: "Session", key: str) -> str | None:
    """Synchronous version of get_setting for use in Celery tasks."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import Session  # noqa: F401 — type hint only
    result = db.execute(sa_select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.is_encrypted and row.value:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value
```

Also export the new constants from the module (they're already module-level so no extra action needed — just confirm `JENKINS_INGEST_SECRET` is importable).

- [ ] **Step 2: Write a failing unit test for get_setting_sync**

Add to `tests/unit/test_digest_svc.py`:

```python
from unittest.mock import MagicMock, patch


def test_get_setting_sync_returns_none_when_missing():
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = get_setting_sync(mock_db, "nonexistent_key")
    assert result is None


def test_get_setting_sync_returns_plaintext():
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    row = MagicMock(spec=PlatformSetting)
    row.is_encrypted = False
    row.value = "smtp.example.com"

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = row

    result = get_setting_sync(mock_db, "smtp_host")
    assert result == "smtp.example.com"
```

- [ ] **Step 3: Run the new tests — they should fail first**

```bash
source .venv/bin/activate && pytest tests/unit/test_digest_svc.py -v
```

Expected: FAILED (function not yet implemented)

- [ ] **Step 4: Implement get_setting_sync (already written in Step 1)**

Re-run:

```bash
source .venv/bin/activate && pytest tests/unit/test_digest_svc.py -v
```

Expected: PASSED

- [ ] **Step 5: Extend PlatformSettingsUpdate and PlatformSettingsResponse in ansible.py**

Replace the existing `PlatformSettingsUpdate` class with:

```python
class PlatformSettingsUpdate(BaseModel):
    salt_master_address: str | None = None
    kri_api_url: str | None = None
    ssh_bootstrap_username: str | None = None
    ssh_bootstrap_password: str | None = None
    ansible_endpoint_url: str | None = None
    ansible_api_token: str | None = None
    playbooks_dir: str | None = None
    pillar_dir: str | None = None
    cxone_url: str | None = None
    cxone_api_token: str | None = None
    sonarqube_url: str | None = None
    sonarqube_token: str | None = None
    license_policy: str | None = None
    vnc_enabled: bool = False
    # Email digest
    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    digest_recipients: str | None = None
    # Jenkins
    jenkins_ingest_secret: str | None = None
```

Replace the existing `PlatformSettingsResponse` class with:

```python
class PlatformSettingsResponse(BaseModel):
    salt_master_address: str | None
    kri_api_url: str | None = None
    ssh_bootstrap_username: str | None
    ssh_bootstrap_password: None = None
    controller_pubkey: str | None
    ansible_endpoint_url: str | None = None
    ansible_api_token: None = None
    playbooks_dir: str | None = None
    pillar_dir: str | None = None
    cxone_url: str | None = None
    sonarqube_url: str | None = None
    license_policy: str | None = None
    vnc_enabled: bool = False
    # Email digest (never return secrets)
    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_username: str | None = None
    smtp_password: None = None
    smtp_from: str | None = None
    digest_recipients: str | None = None
    # Jenkins (never return secret)
    jenkins_ingest_secret: None = None
```

- [ ] **Step 6: Update platform_settings.py route to handle new fields**

In `get_settings`, add reads for the new settings after the existing `vnc_enabled_raw` block:

```python
@router.get("", response_model=PlatformSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()
    vnc_enabled_raw = await get_setting(db, VNC_ENABLED)
    vnc_enabled = vnc_enabled_raw == "true"
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        kri_api_url=await get_setting(db, KRI_API_URL),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        controller_pubkey=get_controller_pubkey(),
        ansible_endpoint_url=await get_setting(db, ANSIBLE_ENDPOINT_URL),
        playbooks_dir=await get_setting(db, PLAYBOOKS_DIR),
        pillar_dir=await get_setting(db, PILLAR_DIR),
        cxone_url=await get_setting(db, CXONE_URL),
        sonarqube_url=await get_setting(db, SONARQUBE_URL),
        license_policy=await get_setting(db, LICENSE_POLICY),
        vnc_enabled=vnc_enabled,
        smtp_host=await get_setting(db, SMTP_HOST),
        smtp_port=await get_setting(db, SMTP_PORT),
        smtp_username=await get_setting(db, SMTP_USERNAME),
        smtp_from=await get_setting(db, SMTP_FROM),
        digest_recipients=await get_setting(db, DIGEST_RECIPIENTS),
    )
```

In `update_settings`, import the new constants at the top of the file (add to existing import block):

```python
from fleet_platform.services.platform_settings_svc import (
    ...existing imports...,
    DIGEST_RECIPIENTS,
    JENKINS_INGEST_SECRET,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    ...
)
```

Then add handling for new fields inside `update_settings` before the final `return`:

```python
    if payload.smtp_host is not None:
        await set_setting(db, SMTP_HOST, payload.smtp_host)
    if payload.smtp_port is not None:
        await set_setting(db, SMTP_PORT, payload.smtp_port)
    if payload.smtp_username is not None:
        await set_setting(db, SMTP_USERNAME, payload.smtp_username)
    if payload.smtp_password:
        await set_setting(db, SMTP_PASSWORD, payload.smtp_password, encrypt=True)
    if payload.smtp_from is not None:
        await set_setting(db, SMTP_FROM, payload.smtp_from)
    if payload.digest_recipients is not None:
        await set_setting(db, DIGEST_RECIPIENTS, payload.digest_recipients)
    if payload.jenkins_ingest_secret:
        await set_setting(db, JENKINS_INGEST_SECRET, payload.jenkins_ingest_secret, encrypt=True)
```

Update the `return PlatformSettingsResponse(...)` inside `update_settings` to include the new fields (same as `get_settings` above).

- [ ] **Step 7: Update frontend TypeScript types in ansible.ts**

In `frontend/src/api/ansible.ts`, update the `PlatformSettings` interface:

```typescript
export interface PlatformSettings {
  salt_master_address: string | null
  kri_api_url: string | null
  ssh_bootstrap_username: string | null
  ssh_bootstrap_password: null
  controller_pubkey: string | null
  ansible_endpoint_url: string | null
  playbooks_dir: string | null
  pillar_dir: string | null
  cxone_url: string | null
  sonarqube_url: string | null
  license_policy: string | null
  vnc_enabled?: boolean
  // Email digest
  smtp_host: string | null
  smtp_port: string | null
  smtp_username: string | null
  smtp_password: null
  smtp_from: string | null
  digest_recipients: string | null
  // Jenkins
  jenkins_ingest_secret: null
}
```

Update the `updateSettings` payload type to include the new optional fields:

```typescript
updateSettings: (payload: {
    salt_master_address?: string
    kri_api_url?: string
    ssh_bootstrap_username?: string
    ssh_bootstrap_password?: string
    ansible_endpoint_url?: string
    ansible_api_token?: string
    playbooks_dir?: string
    pillar_dir?: string
    cxone_url?: string
    cxone_api_token?: string
    sonarqube_url?: string
    sonarqube_token?: string
    license_policy?: string
    vnc_enabled?: boolean
    // Email digest
    smtp_host?: string
    smtp_port?: string
    smtp_username?: string
    smtp_password?: string
    smtp_from?: string
    digest_recipients?: string
    // Jenkins
    jenkins_ingest_secret?: string
  }) => api.put<PlatformSettings>('/api/v1/settings', payload),
```

- [ ] **Step 8: Run unit tests and frontend type check**

```bash
source .venv/bin/activate && pytest tests/unit/ -q
```

Expected: All pass.

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: 0 type errors.

- [ ] **Step 9: Commit**

```bash
git add fleet_platform/services/platform_settings_svc.py \
        fleet_platform/schemas/ansible.py \
        fleet_platform/api/routes/platform_settings.py \
        frontend/src/api/ansible.ts \
        tests/unit/test_digest_svc.py
git commit -m "feat: add SMTP and Jenkins ingest settings to platform settings"
```

---

## Task 4: Email digest service

**Files:**
- Create: `fleet_platform/services/digest_svc.py`
- Test: `tests/unit/test_digest_svc.py` — expand with real tests

- [ ] **Step 1: Write failing tests for digest_svc**

Replace the content of `tests/unit/test_digest_svc.py` with:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_db(builds=None, total_nodes=5, online_nodes=3):
    """Build a mock sync SQLAlchemy Session returning test data."""
    from unittest.mock import MagicMock
    db = MagicMock()

    build_list = builds or []

    call_count = {"n": 0}

    def execute_side_effect(stmt):
        call_count["n"] += 1
        mock_result = MagicMock()

        # First call: builds query
        if call_count["n"] == 1:
            mock_result.scalars.return_value.all.return_value = build_list
        # Second call: total_nodes count
        elif call_count["n"] == 2:
            mock_result.scalar_one.return_value = total_nodes
        # Third call: online_nodes count
        else:
            mock_result.scalar_one.return_value = online_nodes

        return mock_result

    db.execute.side_effect = execute_side_effect
    return db


def _make_build(job_name="test-job", build_number=1, result="SUCCESS"):
    mock = MagicMock()
    mock.job_name = job_name
    mock.build_number = build_number
    mock.result = result
    mock.started_at = datetime.now(UTC)
    return mock


def test_get_week_stats_empty_builds():
    from fleet_platform.services.digest_svc import get_week_stats

    db = _make_db(builds=[], total_nodes=10, online_nodes=7)
    stats = get_week_stats(db)

    assert stats["builds_total"] == 0
    assert stats["builds_passed"] == 0
    assert stats["builds_failed"] == 0
    assert stats["top_failing_jobs"] == []
    assert stats["total_nodes"] == 10
    assert stats["online_nodes"] == 7


def test_get_week_stats_counts_failures():
    from fleet_platform.services.digest_svc import get_week_stats

    builds = [
        _make_build("job-a", 1, "SUCCESS"),
        _make_build("job-a", 2, "FAILURE"),
        _make_build("job-a", 3, "FAILURE"),
        _make_build("job-b", 1, "FAILURE"),
        _make_build("job-b", 2, "SUCCESS"),
    ]
    db = _make_db(builds=builds)
    stats = get_week_stats(db)

    assert stats["builds_total"] == 5
    assert stats["builds_passed"] == 2
    assert stats["builds_failed"] == 3
    # job-a has 2 failures, job-b has 1 — job-a should be first
    assert stats["top_failing_jobs"][0] == ("job-a", 2)
    assert stats["top_failing_jobs"][1] == ("job-b", 1)


def test_get_week_stats_unstable_counts_as_failed():
    from fleet_platform.services.digest_svc import get_week_stats

    builds = [_make_build("job-x", 1, "UNSTABLE")]
    db = _make_db(builds=builds)
    stats = get_week_stats(db)

    assert stats["builds_failed"] == 1
    assert stats["top_failing_jobs"][0][0] == "job-x"


def test_render_html_contains_stats():
    from fleet_platform.services.digest_svc import render_html

    stats = {
        "builds_total": 42,
        "builds_passed": 38,
        "builds_failed": 4,
        "top_failing_jobs": [("deploy-prod", 3), ("ci-lint", 1)],
        "total_nodes": 20,
        "online_nodes": 18,
        "period_start": "2026-05-20",
        "period_end": "2026-05-27",
    }
    html = render_html(stats)

    assert "42" in html
    assert "38" in html
    assert "4" in html
    assert "deploy-prod" in html
    assert "20" in html
    assert "18" in html
    assert "90%" in html  # pass rate: 38/42 = ~90%


def test_render_html_no_failures():
    from fleet_platform.services.digest_svc import render_html

    stats = {
        "builds_total": 10,
        "builds_passed": 10,
        "builds_failed": 0,
        "top_failing_jobs": [],
        "total_nodes": 5,
        "online_nodes": 5,
        "period_start": "2026-05-20",
        "period_end": "2026-05-27",
    }
    html = render_html(stats)
    assert "No failures" in html


def test_send_digest_raises_when_smtp_not_configured():
    from fleet_platform.services.digest_svc import send_digest

    db = MagicMock()
    with patch("fleet_platform.services.digest_svc.get_setting_sync", return_value=None):
        with pytest.raises(ValueError, match="SMTP host not configured"):
            send_digest(db)


def test_send_digest_raises_when_no_recipients():
    from fleet_platform.services.digest_svc import send_digest

    def mock_get_setting(db, key):
        if key == "smtp_host":
            return "smtp.example.com"
        if key == "digest_recipients":
            return ""
        return None

    with patch("fleet_platform.services.digest_svc.get_setting_sync", side_effect=mock_get_setting):
        with pytest.raises(ValueError, match="No digest recipients"):
            send_digest(MagicMock())


def test_get_setting_sync_returns_none_when_missing():
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = get_setting_sync(mock_db, "nonexistent_key")
    assert result is None


def test_get_setting_sync_returns_plaintext():
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    row = MagicMock(spec=PlatformSetting)
    row.is_encrypted = False
    row.value = "smtp.example.com"

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = row

    result = get_setting_sync(mock_db, "smtp_host")
    assert result == "smtp.example.com"
```

- [ ] **Step 2: Run — confirm failures**

```bash
source .venv/bin/activate && pytest tests/unit/test_digest_svc.py -v
```

Expected: FAILED (ImportError on `fleet_platform.services.digest_svc`)

- [ ] **Step 3: Create the digest service**

```python
# fleet_platform/services/digest_svc.py
import smtplib
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
from fleet_platform.models.node import Node
from fleet_platform.services.platform_settings_svc import (
    DIGEST_RECIPIENTS,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    decrypt_secret,
    get_setting_sync,
)


def get_week_stats(db: Session) -> dict:
    since = datetime.now(UTC) - timedelta(days=7)
    builds = db.execute(
        select(JenkinsBuildEvent).where(JenkinsBuildEvent.started_at >= since)
    ).scalars().all()

    total = len(builds)
    passed = sum(1 for b in builds if b.result == "SUCCESS")
    failed = sum(1 for b in builds if b.result in ("FAILURE", "UNSTABLE"))

    fail_counts: dict[str, int] = {}
    for b in builds:
        if b.result in ("FAILURE", "UNSTABLE"):
            fail_counts[b.job_name] = fail_counts.get(b.job_name, 0) + 1
    top_failing = sorted(fail_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    total_nodes: int = db.execute(select(func.count(Node.id))).scalar_one()
    online_nodes: int = db.execute(
        select(func.count(Node.id)).where(Node.status == "online")
    ).scalar_one()

    return {
        "builds_total": total,
        "builds_passed": passed,
        "builds_failed": failed,
        "top_failing_jobs": top_failing,
        "total_nodes": total_nodes,
        "online_nodes": online_nodes,
        "period_start": since.strftime("%Y-%m-%d"),
        "period_end": datetime.now(UTC).strftime("%Y-%m-%d"),
    }


def render_html(stats: dict) -> str:
    top_failing_rows = "".join(
        f'<tr>'
        f'<td style="padding:6px 12px;border-bottom:1px solid #E5E7EB;font-size:13px;color:#111827">{name}</td>'
        f'<td style="padding:6px 12px;border-bottom:1px solid #E5E7EB;text-align:right;color:#DC2626;font-weight:600;font-size:13px">{count}</td>'
        f'</tr>'
        for name, count in stats["top_failing_jobs"]
    ) or '<tr><td colspan="2" style="padding:8px 12px;font-size:13px;color:#6B7280">No failures this week</td></tr>'

    pass_rate = (
        round(stats["builds_passed"] / stats["builds_total"] * 100)
        if stats["builds_total"] > 0
        else 100
    )

    fail_bg = "#FEF2F2" if stats["builds_failed"] > 0 else "#F9FAFB"
    fail_border = "#FECACA" if stats["builds_failed"] > 0 else "#E5E7EB"
    fail_color = "#DC2626" if stats["builds_failed"] > 0 else "#111827"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Fleet Digest</title></head>
<body style="margin:0;padding:0;background:#F9FAFB;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F9FAFB;padding:32px 16px">
<tr><td>
  <table width="600" cellpadding="0" cellspacing="0"
         style="margin:0 auto;background:#FFFFFF;border-radius:12px;border:1px solid #E5E7EB;overflow:hidden">

    <tr><td style="background:#1D4ED8;padding:24px 32px">
      <p style="margin:0;font-size:12px;font-weight:600;color:#93C5FD;text-transform:uppercase;letter-spacing:0.05em">kri Fleet Platform</p>
      <h1 style="margin:6px 0 0;color:#FFFFFF;font-size:22px;font-weight:700">Weekly Fleet Digest</h1>
      <p style="margin:4px 0 0;color:#BFDBFE;font-size:13px">{stats['period_start']} — {stats['period_end']}</p>
    </td></tr>

    <tr><td style="padding:24px 32px">
      <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#111827">Fleet Health</h2>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="50%" style="padding-right:8px">
            <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#16A34A">{stats['online_nodes']}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Nodes Online</div>
            </div>
          </td>
          <td width="50%" style="padding-left:8px">
            <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#111827">{stats['total_nodes']}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Total Nodes</div>
            </div>
          </td>
        </tr>
      </table>
    </td></tr>

    <tr><td style="padding:0 32px"><div style="border-top:1px solid #E5E7EB"></div></td></tr>

    <tr><td style="padding:24px 32px">
      <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#111827">Jenkins Builds — Last 7 Days</h2>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="33%" style="padding-right:6px">
            <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#111827">{stats['builds_total']}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Total Builds</div>
            </div>
          </td>
          <td width="33%" style="padding:0 3px">
            <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#16A34A">{stats['builds_passed']}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Passed</div>
            </div>
          </td>
          <td width="33%" style="padding-left:6px">
            <div style="background:{fail_bg};border:1px solid {fail_border};border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:{fail_color}">{stats['builds_failed']}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Failed</div>
            </div>
          </td>
        </tr>
      </table>
      <div style="margin-top:12px;background:#EFF6FF;border-radius:6px;padding:10px 16px;font-size:13px;color:#1D4ED8;text-align:center">
        Pass rate this week: <strong>{pass_rate}%</strong>
      </div>
    </td></tr>

    <tr><td style="padding:0 32px 24px">
      <h2 style="margin:0 0 12px;font-size:15px;font-weight:600;color:#111827">Top Failing Jobs</h2>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #E5E7EB;border-radius:8px;overflow:hidden">
        <tr style="background:#F9FAFB">
          <th style="padding:8px 12px;text-align:left;font-size:12px;font-weight:600;color:#6B7280;border-bottom:1px solid #E5E7EB">Job</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#6B7280;border-bottom:1px solid #E5E7EB">Failures</th>
        </tr>
        {top_failing_rows}
      </table>
    </td></tr>

    <tr><td style="background:#F9FAFB;border-top:1px solid #E5E7EB;padding:16px 32px;text-align:center">
      <p style="margin:0;font-size:12px;color:#6B7280">
        Generated by <strong>kri Fleet Platform</strong> · Weekly digest every Monday 08:00 UTC
      </p>
    </td></tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


def send_digest(db: Session) -> dict:
    smtp_host = get_setting_sync(db, SMTP_HOST)
    if not smtp_host:
        raise ValueError("SMTP host not configured")

    smtp_port = int(get_setting_sync(db, SMTP_PORT) or "587")
    smtp_user = get_setting_sync(db, SMTP_USERNAME)
    smtp_password_raw = get_setting_sync(db, SMTP_PASSWORD)
    smtp_password = decrypt_secret(smtp_password_raw) if smtp_password_raw else ""
    from_addr = get_setting_sync(db, SMTP_FROM) or smtp_user or ""
    recipients_raw = get_setting_sync(db, DIGEST_RECIPIENTS) or ""
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients:
        raise ValueError("No digest recipients configured")

    stats = get_week_stats(db)
    html = render_html(stats)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Fleet Digest — Week ending {stats['period_end']}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.sendmail(from_addr, recipients, msg.as_string())

    return {"status": "sent", "recipients": len(recipients), **stats}
```

- [ ] **Step 4: Run unit tests**

```bash
source .venv/bin/activate && pytest tests/unit/test_digest_svc.py -v
```

Expected: All PASSED (8+ tests)

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/digest_svc.py \
        tests/unit/test_digest_svc.py
git commit -m "feat: add email digest service with HTML renderer and SMTP sender"
```

---

## Task 5: Celery beat task + admin trigger endpoint

**Files:**
- Create: `fleet_platform/workers/digest_tasks.py`
- Modify: `fleet_platform/workers/celery_app.py`
- Modify: `fleet_platform/api/routes/builds.py` — add `POST /api/v1/digest/send-now`

- [ ] **Step 1: Create the Celery digest task**

```python
# fleet_platform/workers/digest_tasks.py
"""Weekly fleet digest email task."""
import logging

from fleet_platform.db.session import get_sync_db
from fleet_platform.services.digest_svc import send_digest
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="fleet_platform.workers.digest_tasks.weekly_digest",
    queue="maintenance",
)
def weekly_digest() -> dict:
    """Send the weekly fleet + Jenkins build digest email.

    Scheduled: every Monday 08:00 UTC via Celery beat.
    Also callable on-demand via POST /api/v1/digest/send-now.
    """
    logger.info("weekly_digest: starting")
    with get_sync_db() as db:
        result = send_digest(db)
    logger.info("weekly_digest: sent to %d recipients", result.get("recipients", 0))
    return result
```

- [ ] **Step 2: Register the task and beat schedule in celery_app.py**

In `fleet_platform/workers/celery_app.py`, add `"fleet_platform.workers.digest_tasks"` to the `include` list:

```python
celery_app = Celery(
    "fleet_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "fleet_platform.workers.drift_tasks",
        "fleet_platform.workers.sbom_tasks",
        "fleet_platform.workers.maintenance",
        "fleet_platform.workers.ansible_tasks",
        "fleet_platform.workers.playbook_tasks",
        "fleet_platform.workers.security_tasks",
        "fleet_platform.workers.salt_tasks",
        "fleet_platform.workers.alert_tasks",
        "fleet_platform.workers.ios_tasks",
        "fleet_platform.workers.health_tasks",
        "fleet_platform.workers.digest_tasks",  # ← add this
    ],
)
```

In the `beat_schedule` dict, add the weekly digest entry:

```python
        "weekly-fleet-digest": {
            "task": "fleet_platform.workers.digest_tasks.weekly_digest",
            "schedule": crontab(hour=8, minute=0, day_of_week=1),  # Monday 08:00 UTC
        },
```

- [ ] **Step 3: Add the admin trigger endpoint to builds.py**

Append to `fleet_platform/api/routes/builds.py`:

```python
@router.post("/digest/send-now")
async def trigger_digest_now(
    _: dict = Depends(require_role("admin")),
):
    """Trigger the weekly digest immediately. Dispatches as a Celery task (returns task_id)."""
    from fleet_platform.workers.digest_tasks import weekly_digest
    task = weekly_digest.delay()
    return {"status": "queued", "task_id": task.id}
```

**Note:** The router prefix is `/api/v1/builds`, so this endpoint becomes `POST /api/v1/builds/digest/send-now`. The frontend will call this URL.

- [ ] **Step 4: Verify the task can be imported**

```bash
source .venv/bin/activate && python -c "
from fleet_platform.workers.digest_tasks import weekly_digest
print('task name:', weekly_digest.name)
"
```

Expected: `task name: fleet_platform.workers.digest_tasks.weekly_digest`

- [ ] **Step 5: Verify beat schedule is registered**

```bash
source .venv/bin/activate && python -c "
from fleet_platform.workers.celery_app import celery_app
print(list(celery_app.conf.beat_schedule.keys()))
"
```

Expected output includes `"weekly-fleet-digest"`.

- [ ] **Step 6: Run full unit test suite**

```bash
source .venv/bin/activate && pytest tests/unit/ -q
```

Expected: 0 failures

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/workers/digest_tasks.py \
        fleet_platform/workers/celery_app.py \
        fleet_platform/api/routes/builds.py
git commit -m "feat: add weekly_digest Celery beat task and admin send-now trigger"
```

---

## Task 6: Frontend — Notifications settings tab + builds API client

**Files:**
- Create: `frontend/src/api/builds.ts`
- Modify: `frontend/src/pages/SettingsPage.tsx` — add "Notifications" tab

- [ ] **Step 1: Create the builds API client**

```typescript
// frontend/src/api/builds.ts
import { api } from './client'

export interface JenkinsBuild {
  id: string
  job_name: string
  build_number: number
  result: 'SUCCESS' | 'FAILURE' | 'UNSTABLE' | 'ABORTED' | 'NOT_BUILT'
  duration_ms: number | null
  started_at: string
  test_pass: number | null
  test_fail: number | null
  test_total: number | null
  node_name: string | null
  branch: string | null
}

export const buildsApi = {
  listRecent: (limit = 50) =>
    api.get<JenkinsBuild[]>(`/api/v1/builds/recent?limit=${limit}`),
  triggerDigest: () =>
    api.post<{ status: string; task_id: string }>('/api/v1/builds/digest/send-now', {}),
}
```

- [ ] **Step 2: Add state variables for new settings fields in SettingsPage.tsx**

At the top of the `SettingsPage` function, after the existing `useState` declarations, add:

```typescript
  // Email digest settings
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState('587')
  const [smtpUsername, setSmtpUsername] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [smtpFrom, setSmtpFrom] = useState('')
  const [digestRecipients, setDigestRecipients] = useState('')
  const [jenkinsSecret, setJenkinsSecret] = useState('')
  const [digestSending, setDigestSending] = useState(false)
```

- [ ] **Step 3: Populate state from API data in the useEffect**

Inside the existing `useEffect` that reads `data`, add after the existing `if` blocks:

```typescript
      if (data.smtp_host) setSmtpHost(data.smtp_host)
      if (data.smtp_port) setSmtpPort(data.smtp_port)
      if (data.smtp_username) setSmtpUsername(data.smtp_username)
      if (data.smtp_from) setSmtpFrom(data.smtp_from)
      if (data.digest_recipients) setDigestRecipients(data.digest_recipients)
```

- [ ] **Step 4: Include new fields in the saveMutation**

In `saveMutation.mutationFn`, add the new fields to the `ansibleApi.updateSettings` call:

```typescript
      smtp_host: smtpHost || undefined,
      smtp_port: smtpPort || undefined,
      smtp_username: smtpUsername || undefined,
      smtp_password: smtpPassword || undefined,
      smtp_from: smtpFrom || undefined,
      digest_recipients: digestRecipients || undefined,
      jenkins_ingest_secret: jenkinsSecret || undefined,
```

- [ ] **Step 5: Add "Notifications" to the TABS array**

Find the line:
```typescript
  const TABS = ['General', 'Bootstrap', 'Remote Access', 'Integrations', 'Advanced', 'AI / LLM'] as const
```

Replace with:
```typescript
  const TABS = ['General', 'Bootstrap', 'Remote Access', 'Integrations', 'Advanced', 'AI / LLM', 'Notifications'] as const
```

- [ ] **Step 6: Add the Notifications tab panel**

Import `buildsApi` at the top of SettingsPage.tsx:

```typescript
import { buildsApi } from '../api/builds'
```

Then, at the bottom of the JSX (before the closing `</div>` of the outer `space-y-6` div), add the Notifications tab panel. Find the last `{activeTab === 'AI / LLM' && (` block and add after its closing `)}`:

```tsx
      {/* Notifications tab */}
      {activeTab === 'Notifications' && (
        <div className="space-y-6">

          {/* Jenkins Ingest */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Jenkins Build Ingest</h2>
              <p className="text-sm text-gray-500 mt-1">
                Configure your Jenkins jobs to POST build results to kri after each build.
                No polling — Jenkins pushes data to you.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Ingest Endpoint
              </label>
              <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2">
                <code className="text-xs font-mono text-brand-700 truncate">
                  {kriApiUrl ? `${kriApiUrl.replace(/\/$/, '')}/api/v1/builds/ingest` : 'Set kri server URL in General tab first'}
                </code>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Shared Secret (X-Jenkins-Secret header)
              </label>
              <input
                type="password"
                value={jenkinsSecret}
                onChange={(e) => setJenkinsSecret(e.target.value)}
                placeholder="Enter new secret to set or rotate"
                className={inputClass}
              />
              <p className="text-xs text-gray-400 mt-1">
                Set this once, copy it to Jenkins as a credential, then add it to each job's
                <code className="mx-1 text-xs bg-gray-100 px-1 rounded">X-Jenkins-Secret</code>
                header. Secret is stored encrypted.
              </p>
            </div>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm font-semibold text-blue-900 mb-2">Jenkins Pipeline Snippet</p>
              <pre className="text-xs font-mono text-blue-800 overflow-x-auto whitespace-pre">{`post {
  always {
    script {
      def payload = groovy.json.JsonOutput.toJson([
        job_name    : env.JOB_NAME,
        build_number: env.BUILD_NUMBER.toInteger(),
        result      : currentBuild.result ?: 'SUCCESS',
        duration_ms : currentBuild.duration,
        started_at  : new Date(currentBuild.startTimeInMillis)
                        .format("yyyy-MM-dd'T'HH:mm:ss'Z'",
                                TimeZone.getTimeZone('UTC')),
        test_pass   : currentBuild.testResultAction?.passCount,
        test_fail   : currentBuild.testResultAction?.failCount,
        test_total  : currentBuild.testResultAction?.totalCount,
        node_name   : env.NODE_NAME,
        branch      : env.GIT_BRANCH,
      ])
      httpRequest(
        url         : "\${env.KRI_API_URL}/api/v1/builds/ingest",
        httpMode    : 'POST',
        contentType : 'APPLICATION_JSON',
        requestBody : payload,
        customHeaders: [[name: 'X-Jenkins-Secret',
                         value: env.KRI_JENKINS_SECRET]],
        validResponseCodes: '200'
      )
    }
  }
}`}</pre>
              <p className="text-xs text-blue-700 mt-2">
                Add <code className="bg-blue-100 px-1 rounded">KRI_API_URL</code> and{' '}
                <code className="bg-blue-100 px-1 rounded">KRI_JENKINS_SECRET</code> as Jenkins
                credentials (Secret Text). Requires the{' '}
                <a
                  href="https://plugins.jenkins.io/http_request/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >HTTP Request Plugin</a>.
              </p>
            </div>
          </div>

          {/* SMTP settings */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Email (SMTP)</h2>
              <p className="text-sm text-gray-500 mt-1">
                Settings for the weekly fleet digest email. Sent every Monday at 08:00 UTC.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Host</label>
                <input
                  type="text"
                  value={smtpHost}
                  onChange={(e) => setSmtpHost(e.target.value)}
                  placeholder="smtp.gmail.com"
                  className={monoInputClass}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
                <input
                  type="text"
                  value={smtpPort}
                  onChange={(e) => setSmtpPort(e.target.value)}
                  placeholder="587"
                  className={monoInputClass}
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Username</label>
              <input
                type="text"
                value={smtpUsername}
                onChange={(e) => setSmtpUsername(e.target.value)}
                placeholder="alerts@yourorg.com"
                className={monoInputClass}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Password</label>
              <input
                type="password"
                value={smtpPassword}
                onChange={(e) => setSmtpPassword(e.target.value)}
                placeholder="Enter password to set or update"
                className={inputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Stored encrypted. Leave blank to keep existing.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">From Address</label>
              <input
                type="text"
                value={smtpFrom}
                onChange={(e) => setSmtpFrom(e.target.value)}
                placeholder="kri Fleet Platform <kri@yourorg.com>"
                className={monoInputClass}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Digest Recipients
              </label>
              <input
                type="text"
                value={digestRecipients}
                onChange={(e) => setDigestRecipients(e.target.value)}
                placeholder="manager@yourorg.com, cto@yourorg.com"
                className={monoInputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Comma-separated list of email addresses.</p>
            </div>
          </div>

          {/* Save + Test */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
            <div className="flex items-center gap-3">
              <button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
              >
                {saveMutation.isPending ? 'Saving…' : 'Save Notification Settings'}
              </button>
              <button
                onClick={async () => {
                  setDigestSending(true)
                  try {
                    await buildsApi.triggerDigest()
                    toast('Digest queued — check your inbox in a moment')
                  } catch {
                    toast('Failed to queue digest', 'error')
                  } finally {
                    setDigestSending(false)
                  }
                }}
                disabled={digestSending}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 disabled:opacity-50 border border-gray-200"
              >
                {digestSending ? 'Sending…' : 'Send Test Digest Now'}
              </button>
            </div>
          </div>

        </div>
      )}
```

- [ ] **Step 7: Run frontend type check**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: 0 type errors, successful build.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/builds.ts \
        frontend/src/pages/SettingsPage.tsx
git commit -m "feat: add Notifications settings tab with SMTP and Jenkins ingest config"
```

---

## Task 7: Final sweep, integration tests, and PR

**Files:**
- Test: `tests/integration/test_builds_ingest.py` — verify all tests pass
- Test: `tests/unit/test_digest_svc.py` — full suite passes

- [ ] **Step 1: Run full unit test suite**

```bash
source .venv/bin/activate && pytest tests/unit/ -q
```

Expected: 0 failures

- [ ] **Step 2: Run integration tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_builds_ingest.py -v
```

Expected: 4 tests, all PASSED

- [ ] **Step 3: Run full integration suite to check for regressions**

```bash
source .venv/bin/activate && pytest tests/integration/ -q
```

Expected: 0 failures

- [ ] **Step 4: Run frontend build**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: Compiled successfully, 0 type errors

- [ ] **Step 5: Smoke-test the ingest endpoint manually**

```bash
source .venv/bin/activate && python -c "
import asyncio, httpx, json
from datetime import UTC, datetime

async def test():
    # First set the secret in DB
    from fleet_platform.db.session import get_sync_db
    from fleet_platform.models.platform_setting import PlatformSetting
    with get_sync_db() as db:
        existing = db.query(PlatformSetting).filter_by(key='jenkins_ingest_secret').first()
        if not existing:
            db.add(PlatformSetting(key='jenkins_ingest_secret', value='test123', is_encrypted=False))
            db.commit()
            print('Set secret to test123')

    async with httpx.AsyncClient(base_url='http://localhost:8000') as client:
        payload = {
            'job_name': 'smoke-test',
            'build_number': 1,
            'result': 'SUCCESS',
            'started_at': datetime.now(UTC).isoformat(),
        }
        r = await client.post('/api/v1/builds/ingest', json=payload,
                              headers={'X-Jenkins-Secret': 'test123'})
        print('Status:', r.status_code, r.json())

asyncio.run(test())
"
```

Expected: `Status: 200 {'status': 'ok', 'id': '<uuid>'}`

- [ ] **Step 6: Verify the Notifications tab in the browser**

Start the dev server (if not already running) and navigate to Settings → Notifications tab. Confirm:
- Jenkins ingest URL is shown (uses kriApiUrl from General tab)
- SMTP fields are present and save correctly
- "Send Test Digest Now" button is visible

- [ ] **Step 7: Close issue #34 (SSH terminal already shipped)**

```bash
gh issue close 34 --comment "SSH terminal was shipped in PR #36 (multi-session tabbed SSH). Closing."
```

- [ ] **Step 8: Open the PR**

```bash
gh pr create \
  --title "feat: Jenkins build ingest + weekly email digest (#7)" \
  --body "$(cat <<'EOF'
## Summary

- Jenkins jobs POST build results to `POST /api/v1/builds/ingest` using a shared secret (`X-Jenkins-Secret` header) — no API tokens needed
- Build events stored in `jenkins_build_events` table (migration 021), idempotent on `(job_name, build_number)`
- Weekly HTML email digest sent every Monday 08:00 UTC via Celery beat — shows fleet health + build totals, pass/fail, and top failing jobs
- Admin can trigger digest on-demand via `POST /api/v1/builds/digest/send-now`
- SMTP settings + Jenkins secret stored as encrypted platform settings
- New "Notifications" tab in Settings page with SMTP config, Jenkins ingest URL display, and pipeline snippet

Closes #7

## Test plan

- [ ] Unit tests: `pytest tests/unit/test_digest_svc.py -v` — all pass
- [ ] Integration tests: `pytest tests/integration/test_builds_ingest.py -v` — 4 tests pass
- [ ] Full suite: `pytest tests/unit/ tests/integration/ -q` — 0 failures
- [ ] Frontend build: `cd frontend && npm run build` — 0 type errors
- [ ] Smoke-test ingest endpoint with curl/httpx
- [ ] Visit Settings → Notifications tab in browser
- [ ] Verify "Send Test Digest Now" queues a Celery task

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|-------------|------|
| Jenkins pushes build data to kri (no tokens) | T2 — `POST /api/v1/builds/ingest` with X-Jenkins-Secret |
| Build data: total builds, failed, passed, top issues | T4 — `get_week_stats()` computes all of these |
| Weekly email digest for management | T5 — Celery beat Monday 08:00 UTC |
| Email contains Jenkins build stats | T4 — HTML renderer includes 3-column build stats block |
| Email delivery (SMTP) | T3 + T4 — SMTP settings stored, `send_digest()` uses `smtplib` |
| Admin can trigger digest on demand | T5 — `POST /api/v1/builds/digest/send-now` |
| Jenkins pipeline snippet for integration | T6 — shown in Settings UI |
| Settings UI for SMTP + Jenkins secret | T6 — Notifications tab in SettingsPage |

### Placeholder scan

No TBDs, no "add error handling", no "similar to Task N" references — all tasks have complete code.

### Type consistency

- `JenkinsBuildEvent` model created in T1, imported in T2 (ingest route), T4 (digest_svc), and T5 (task)
- `JENKINS_INGEST_SECRET` constant defined in T3, used in T2 (`builds.py`), T3 (settings route), T5 (digest task is platform-settings-agnostic — reads via `get_setting_sync`)
- `get_setting_sync` added to `platform_settings_svc` in T3, imported in `digest_svc.py` in T4
- `send_digest()` defined in T4, called in T5 (`digest_tasks.py`)
- `buildsApi.triggerDigest()` defined in T6 `builds.ts`, called in T6 `SettingsPage.tsx`
- `PlatformSettingsResponse` and `PlatformSettingsUpdate` extended in T3 (`ansible.py`), consumed by T3 route and T6 frontend
