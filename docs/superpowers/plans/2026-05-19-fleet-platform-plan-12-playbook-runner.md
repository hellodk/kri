# Fleet Platform Plan 12 — Ansible Playbook & Role Runner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Playbooks page in kri that discovers playbooks and roles from `playbooks/`, shows each role's variables with their defaults, lets operators edit values (committed to git before the run), pick a target (node or group), and triggers execution via ansible-runner — with an optional external Ansible endpoint configurable in Settings.

**Architecture:** A `playbook_discovery` service scans `playbooks/*.yml` and `playbooks/roles/*/` and extracts name, description, and default variables. A `host_vars/` / `group_vars/` directory pattern stores variable overrides; kri commits them before each run. A new `ansible_jobs` table (migration 004) tracks runs. The `run_playbook` Celery task resolves the target, optionally commits var files, builds a static inventory, and runs ansible-runner. The frontend shows role/playbook cards with a Run modal that presents an editable variable form.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, Celery 5.4, ansible-runner 2.x, PyYAML, gitpython, React 18, TanStack Query 5.

---

## Constraints and design decisions

- **Playbooks live at `playbooks/*.yml`** — each top-level yml is a playbook
- **Roles live at `playbooks/roles/<name>/`** — conventional Ansible role layout; vars discovered from `defaults/main.yml`
- **Variable overrides** written to `playbooks/host_vars/<hostname>.yml` (node target) or `playbooks/group_vars/<groupname>.yml` (group target) and git-committed before each run
- **Git commit** happens inside the Celery task using `gitpython`; requires the repo to have a git user configured (uses `git config user.name/email` from environment or falls back to `kri <kri@localhost>`)
- **External Ansible endpoint** — optional AWX/Tower integration stored in `platform_settings`; when configured, kri POSTs to the Ansible endpoint instead of running ansible-runner locally
- **Static inventory** generated per run into ansible-runner's `private_data_dir`
- **stdout stored in DB** after run completes — polling every 3 s in the frontend
- **Migration 004** — new `ansible_jobs` table

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `fleet_platform/services/playbook_discovery.py` | Scan playbooks + roles, parse vars from YAML |
| Create | `fleet_platform/models/ansible_job.py` | `AnsibleJob` ORM model |
| Create | `fleet_platform/db/migrations/versions/004_ansible_jobs.py` | Migration for `ansible_jobs` table |
| Create | `fleet_platform/schemas/playbook.py` | Pydantic request/response schemas |
| Modify | `fleet_platform/api/routes/ansible.py` | Add list, run, job-status endpoints |
| Modify | `fleet_platform/api/routes/platform_settings.py` | Add `ansible_endpoint_url` + `ansible_api_token` |
| Modify | `fleet_platform/schemas/ansible.py` | Extend PlatformSettingsResponse with new fields |
| Create | `fleet_platform/workers/playbook_tasks.py` | `run_playbook` Celery task |
| Modify | `fleet_platform/workers/celery_app.py` | Import `playbook_tasks` |
| Create | `tests/unit/test_playbook_discovery.py` | Unit tests for discovery |
| Create | `tests/unit/test_playbook_tasks.py` | Unit tests for task |
| Create | `tests/integration/test_playbook_api.py` | Integration tests for endpoints |
| Create | `frontend/src/api/playbooks.ts` | API client for playbooks + jobs |
| Create | `frontend/src/pages/PlaybooksPage.tsx` | Role/playbook cards |
| Create | `frontend/src/pages/PlaybookRunModal.tsx` | Variable editor + target + run |
| Modify | `frontend/src/pages/SettingsPage.tsx` | Add Ansible endpoint section |
| Modify | `frontend/src/App.tsx` | Add `/playbooks` route |
| Modify | `frontend/src/components/Layout/Sidebar.tsx` | Add Playbooks nav link |

---

## Task 1: Playbook + role discovery service

**Files:**
- Create: `fleet_platform/services/playbook_discovery.py`
- Create: `tests/unit/test_playbook_discovery.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_playbook_discovery.py
import textwrap
from pathlib import Path
import pytest
from fleet_platform.services.playbook_discovery import discover_all, PlaybookEntry


@pytest.fixture
def playbooks_dir(tmp_path):
    # Top-level playbook
    (tmp_path / "deploy_config.yml").write_text(textwrap.dedent("""\
        # Description: Push config files to all nodes
        - name: Deploy configuration
          hosts: targets
          vars:
            config_version: "1.0"
            restart_services: true
          tasks: []
    """))
    # Role with defaults
    role_dir = tmp_path / "roles" / "salt_minion"
    (role_dir / "defaults").mkdir(parents=True)
    (role_dir / "tasks").mkdir()
    (role_dir / "defaults" / "main.yml").write_text(textwrap.dedent("""\
        # Default variables for salt_minion role
        salt_master: "10.0.0.1"
        log_level: info
        grains_refresh_interval: 300
    """))
    (role_dir / "tasks" / "main.yml").write_text("---\n- name: Configure Salt\n  debug:\n    msg: ok\n")
    # Role without defaults
    role2 = tmp_path / "roles" / "basic_setup"
    (role2 / "tasks").mkdir(parents=True)
    (role2 / "tasks" / "main.yml").write_text("---\n")
    return tmp_path


def test_discover_finds_top_level_playbook(playbooks_dir):
    result = discover_all(playbooks_dir)
    filenames = {e.filename for e in result}
    assert "deploy_config.yml" in filenames


def test_discover_finds_roles(playbooks_dir):
    result = discover_all(playbooks_dir)
    names = {e.filename for e in result}
    assert "roles/salt_minion" in names
    assert "roles/basic_setup" in names


def test_playbook_extracts_vars(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    entry = result["deploy_config.yml"]
    assert entry.default_vars == {"config_version": "1.0", "restart_services": True}


def test_role_extracts_defaults(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    entry = result["roles/salt_minion"]
    assert entry.default_vars["salt_master"] == "10.0.0.1"
    assert entry.default_vars["log_level"] == "info"
    assert entry.default_vars["grains_refresh_interval"] == 300


def test_role_without_defaults_has_empty_vars(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    entry = result["roles/basic_setup"]
    assert entry.default_vars == {}


def test_discover_description_from_comment(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    assert result["deploy_config.yml"].description == "Push config files to all nodes"


def test_discover_empty_dir(tmp_path):
    assert discover_all(tmp_path) == []


def test_discover_skips_malformed_yaml(tmp_path):
    (tmp_path / "bad.yml").write_text(": : : invalid yaml {{{{")
    assert discover_all(tmp_path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/unit/test_playbook_discovery.py -v 2>&1 | tail -10
```
Expected: `ModuleNotFoundError: No module named 'fleet_platform.services.playbook_discovery'`

- [ ] **Step 3: Implement playbook_discovery.py**

```python
# fleet_platform/services/playbook_discovery.py
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PlaybookEntry:
    filename: str        # "deploy_config.yml" or "roles/salt_minion"
    name: str            # human-readable name
    description: str | None
    entry_type: str      # "playbook" | "role"
    default_vars: dict = field(default_factory=dict)


def _parse_description(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# Description:"):
            return stripped[len("# Description:"):].strip()
    return None


def _discover_playbooks(playbooks_dir: Path) -> list[PlaybookEntry]:
    results = []
    for path in sorted(playbooks_dir.glob("*.yml")):
        try:
            raw = path.read_text()
            data = yaml.safe_load(raw)
            if not isinstance(data, list) or not data:
                continue
            play_name = data[0].get("name", path.stem)
            default_vars = data[0].get("vars", {}) or {}
            results.append(PlaybookEntry(
                filename=path.name,
                name=play_name,
                description=_parse_description(raw),
                entry_type="playbook",
                default_vars=default_vars if isinstance(default_vars, dict) else {},
            ))
        except Exception:
            continue
    return results


def _discover_roles(playbooks_dir: Path) -> list[PlaybookEntry]:
    roles_dir = playbooks_dir / "roles"
    if not roles_dir.is_dir():
        return []
    results = []
    for role_path in sorted(roles_dir.iterdir()):
        if not role_path.is_dir():
            continue
        defaults_path = role_path / "defaults" / "main.yml"
        default_vars: dict = {}
        description: str | None = None
        if defaults_path.exists():
            try:
                raw = defaults_path.read_text()
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    default_vars = parsed
                description = _parse_description(raw)
            except Exception:
                pass
        results.append(PlaybookEntry(
            filename=f"roles/{role_path.name}",
            name=role_path.name.replace("_", " ").title(),
            description=description,
            entry_type="role",
            default_vars=default_vars,
        ))
    return results


def discover_all(playbooks_dir: Path) -> list[PlaybookEntry]:
    return _discover_playbooks(playbooks_dir) + _discover_roles(playbooks_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_playbook_discovery.py -v 2>&1 | tail -10
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/playbook_discovery.py tests/unit/test_playbook_discovery.py
git commit -m "feat(P12-T1): playbook + role discovery with variable extraction"
```

---

## Task 2: AnsibleJob model + migration

**Files:**
- Create: `fleet_platform/models/ansible_job.py`
- Create: `fleet_platform/db/migrations/versions/004_ansible_jobs.py`
- Modify: `fleet_platform/models/__init__.py`

- [ ] **Step 1: Create AnsibleJob model**

```python
# fleet_platform/models/ansible_job.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class AnsibleJob(Base):
    __tablename__ = "ansible_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    playbook: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str] = mapped_column(String(255), nullable=False)
    extravars: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    triggered_by: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    rc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now()
    )

    __table_args__ = (
        Index("idx_ansible_jobs_status", "status", "created_at"),
    )
```

- [ ] **Step 2: Export from models/__init__.py**

Read the file first:
```bash
cat /home/dk/Documents/git/kri/fleet_platform/models/__init__.py
```

Then add this line to the imports (alongside the other model imports):
```python
from fleet_platform.models.ansible_job import AnsibleJob
```

- [ ] **Step 3: Create migration 004**

```python
# fleet_platform/db/migrations/versions/004_ansible_jobs.py
"""Add ansible_jobs table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ansible_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("playbook", sa.String(255), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("target_label", sa.String(255), nullable=False),
        sa.Column("extravars", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("triggered_by", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stdout", sa.Text, nullable=True),
        sa.Column("rc", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_ansible_jobs_status", "ansible_jobs", ["status", "created_at"])


def downgrade():
    op.drop_index("idx_ansible_jobs_status", "ansible_jobs")
    op.drop_table("ansible_jobs")
```

- [ ] **Step 4: Run migration**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
alembic upgrade head 2>&1 | tail -5
```
Expected: `Running upgrade 003 -> 004`

- [ ] **Step 5: Verify**

```bash
PGPASSWORD=fleet psql -h 127.0.0.1 -U fleet fleet_demo -c "\d ansible_jobs" 2>&1 | grep -E "id|playbook|extravars|status"
```
Expected: columns listed including `extravars`

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/models/ansible_job.py fleet_platform/models/__init__.py \
  fleet_platform/db/migrations/versions/004_ansible_jobs.py
git commit -m "feat(P12-T2): AnsibleJob model + migration 004 with extravars JSONB"
```

---

## Task 3: Extend platform settings for Ansible endpoint

**Files:**
- Modify: `fleet_platform/services/platform_settings_svc.py`
- Modify: `fleet_platform/api/routes/platform_settings.py`
- Modify: `fleet_platform/schemas/ansible.py`

- [ ] **Step 1: Add constants to platform_settings_svc.py**

Read the file, then add two new constants after the existing ones:
```python
# In fleet_platform/services/platform_settings_svc.py, add:
ANSIBLE_ENDPOINT_URL = "ansible_endpoint_url"
ANSIBLE_API_TOKEN = "ansible_api_token"
```

- [ ] **Step 2: Extend PlatformSettingsResponse schema**

In `fleet_platform/schemas/ansible.py`, update `PlatformSettingsResponse`:
```python
class PlatformSettingsResponse(BaseModel):
    salt_master_address: str | None
    ssh_bootstrap_username: str | None
    ssh_bootstrap_password: None = None
    controller_pubkey: str | None
    ansible_endpoint_url: str | None = None
    ansible_api_token: None = None   # never returned, write-only
```

Also update `PlatformSettingsUpdate`:
```python
class PlatformSettingsUpdate(BaseModel):
    salt_master_address: str | None = None
    ssh_bootstrap_username: str | None = None
    ssh_bootstrap_password: str | None = None
    ansible_endpoint_url: str | None = None
    ansible_api_token: str | None = None
```

- [ ] **Step 3: Update platform_settings route to handle new fields**

Read `fleet_platform/api/routes/platform_settings.py`. In the `PUT` handler, add after the existing `set_setting` calls:
```python
    if payload.ansible_endpoint_url is not None:
        await set_setting(db, ANSIBLE_ENDPOINT_URL, payload.ansible_endpoint_url)
    if payload.ansible_api_token:
        await set_setting(db, ANSIBLE_API_TOKEN, payload.ansible_api_token, encrypt=True)
```

In the `GET` handler, add to the response construction:
```python
    ansible_endpoint_url = await get_setting(db, ANSIBLE_ENDPOINT_URL)
```
And include it in the returned `PlatformSettingsResponse`.

- [ ] **Step 4: Run existing settings tests to verify no regression**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/integration/test_ansible_api.py tests/unit/test_platform_settings.py -v 2>&1 | tail -10
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/platform_settings_svc.py \
  fleet_platform/schemas/ansible.py fleet_platform/api/routes/platform_settings.py
git commit -m "feat(P12-T3): platform settings — Ansible endpoint URL + token"
```

---

## Task 4: Schemas + API endpoints

**Files:**
- Create: `fleet_platform/schemas/playbook.py`
- Modify: `fleet_platform/api/routes/ansible.py`
- Create: `tests/integration/test_playbook_api.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/integration/test_playbook_api.py
import pytest
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/integration/test_playbook_api.py -v 2>&1 | tail -15
```
Expected: failures (routes don't exist yet)

- [ ] **Step 3: Create schemas**

```python
# fleet_platform/schemas/playbook.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class PlaybookEntryResponse(BaseModel):
    filename: str
    name: str
    description: str | None
    entry_type: str          # "playbook" | "role"
    default_vars: dict


class PlaybookRunRequest(BaseModel):
    playbook: str
    target_type: str          # "node" | "group"
    target_id: str            # UUID as string
    extravars: dict = {}      # user-supplied variable overrides


class PlaybookRunResponse(BaseModel):
    job_id: uuid.UUID
    playbook: str
    target_label: str
    status: str
    message: str


class AnsibleJobResponse(BaseModel):
    id: uuid.UUID
    playbook: str
    target_type: str
    target_label: str
    extravars: dict
    status: str
    triggered_by: str
    started_at: datetime | None
    completed_at: datetime | None
    stdout: str | None
    rc: int | None
    created_at: datetime
```

- [ ] **Step 4: Add endpoints to ansible.py**

In `fleet_platform/api/routes/ansible.py`, add the following additional imports (alongside the existing ones at the top):

```python
import uuid
from pathlib import Path

from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.group import Group
from fleet_platform.schemas.playbook import (
    AnsibleJobResponse, PlaybookEntryResponse, PlaybookRunRequest, PlaybookRunResponse,
)
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.workers.playbook_tasks import run_playbook

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent.parent / "playbooks"
```

Add these three endpoints after the existing bootstrap endpoints:

```python
@router.get("/playbooks", response_model=list[PlaybookEntryResponse])
async def list_playbooks(
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    entries = discover_all(_PLAYBOOKS_DIR)
    return [
        PlaybookEntryResponse(
            filename=e.filename,
            name=e.name,
            description=e.description,
            entry_type=e.entry_type,
            default_vars=e.default_vars,
        )
        for e in entries
    ]


@router.post("/playbooks/run", response_model=PlaybookRunResponse, status_code=202)
async def run_playbook_endpoint(
    payload: PlaybookRunRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    # Sanitise — prevent path traversal
    safe_name = payload.playbook.lstrip("/").replace("..", "")
    entries = discover_all(_PLAYBOOKS_DIR)
    entry = next((e for e in entries if e.filename == safe_name), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Playbook '{safe_name}' not found")

    target_label = payload.target_id
    if payload.target_type == "node":
        node_result = await db.execute(select(Node).where(Node.id == uuid.UUID(payload.target_id)))
        node = node_result.scalar_one_or_none()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        target_label = node.hostname or node.minion_id
    elif payload.target_type == "group":
        grp_result = await db.execute(select(Group).where(Group.id == uuid.UUID(payload.target_id)))
        grp = grp_result.scalar_one_or_none()
        if not grp:
            raise HTTPException(status_code=404, detail="Group not found")
        target_label = grp.name

    job = AnsibleJob(
        playbook=safe_name,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_label=target_label,
        extravars=payload.extravars,
        status="pending",
        triggered_by=claims["sub"],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    run_playbook.delay(str(job.id))

    return PlaybookRunResponse(
        job_id=job.id,
        playbook=safe_name,
        target_label=target_label,
        status="pending",
        message="Playbook queued.",
    )


@router.get("/jobs/{job_id}", response_model=AnsibleJobResponse)
async def get_ansible_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return AnsibleJobResponse(
        id=job.id,
        playbook=job.playbook,
        target_type=job.target_type,
        target_label=job.target_label,
        extravars=job.extravars,
        status=job.status,
        triggered_by=job.triggered_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        stdout=job.stdout,
        rc=job.rc,
        created_at=job.created_at,
    )
```

- [ ] **Step 5: Add `operator_client` to integration conftest if missing**

Read `tests/integration/conftest.py`. If there is no `operator_client` fixture, add:

```python
@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator_client(app_with_test_db, test_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from fleet_platform.models import User
    from fleet_platform.core.auth import create_access_token, hash_password
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        op = User(
            email="operator@test.local",
            password_hash=hash_password("pass"),
            role="operator",
            is_active=True,
        )
        session.add(op)
        await session.commit()
    token = create_access_token({"sub": "operator@test.local", "role": "operator"})
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db), base_url="http://test"
    ) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/integration/test_playbook_api.py -v 2>&1 | tail -15
```
Expected: `7 passed`

- [ ] **Step 7: Run full suite**

```bash
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/schemas/playbook.py fleet_platform/api/routes/ansible.py \
  tests/integration/test_playbook_api.py tests/integration/conftest.py
git commit -m "feat(P12-T4): playbook list + run + job status API with extravars"
```

---

## Task 5: Celery task — git commit vars + run playbook

**Files:**
- Create: `fleet_platform/workers/playbook_tasks.py`
- Modify: `fleet_platform/workers/celery_app.py`
- Create: `tests/unit/test_playbook_tasks.py`

- [ ] **Step 1: Add gitpython dependency**

In `pyproject.toml`, add to dependencies:
```toml
    "gitpython>=3.1.0",
```

Run:
```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate && uv sync
python -c "import git; print('gitpython OK')"
```
Expected: `gitpython OK`

- [ ] **Step 2: Write failing unit tests**

```python
# tests/unit/test_playbook_tasks.py
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


def test_write_static_inventory_single_host(tmp_path):
    from fleet_platform.workers.playbook_tasks import _write_static_inventory
    inv_path = _write_static_inventory(str(tmp_path), [("mac-01", "10.0.1.11", "admin")])
    content = Path(inv_path).read_text()
    assert "[targets]" in content
    assert "mac-01 ansible_host=10.0.1.11 ansible_user=admin" in content


def test_write_static_inventory_multiple_hosts(tmp_path):
    from fleet_platform.workers.playbook_tasks import _write_static_inventory
    hosts = [("mac-01", "10.0.1.11", "admin"), ("mac-02", "10.0.1.12", "admin")]
    inv_path = _write_static_inventory(str(tmp_path), hosts)
    content = Path(inv_path).read_text()
    assert "mac-01 ansible_host=10.0.1.11" in content
    assert "mac-02 ansible_host=10.0.1.12" in content


def test_write_var_file_creates_yaml(tmp_path):
    from fleet_platform.workers.playbook_tasks import _write_var_file
    _write_var_file(tmp_path / "host_vars" / "mac-01.yml", {"log_level": "debug", "timeout": 30})
    content = (tmp_path / "host_vars" / "mac-01.yml").read_text()
    assert "log_level: debug" in content
    assert "timeout: 30" in content


def test_run_playbook_missing_job_returns_early():
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.playbook_tasks import run_playbook
        result = run_playbook(str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["reason"] == "job_not_found"
```

- [ ] **Step 3: Run to verify they fail**

```bash
python -m pytest tests/unit/test_playbook_tasks.py -v 2>&1 | tail -8
```
Expected: `ModuleNotFoundError`

- [ ] **Step 4: Implement playbook_tasks.py**

```python
# fleet_platform/workers/playbook_tasks.py
"""Celery tasks for running arbitrary Ansible playbooks."""
import tempfile
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

import ansible_runner
import yaml as _yaml
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.group import Group, GroupMembership
from fleet_platform.models.node import Node
from fleet_platform.workers.ansible_tasks import _get_bootstrap_settings
from fleet_platform.workers.celery_app import celery_app

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"
_REPO_ROOT = Path(__file__).parent.parent.parent


def _write_static_inventory(tmpdir: str, hosts: list[tuple[str, str, str]]) -> str:
    lines = ["[targets]"]
    for hostname, ip, user in hosts:
        lines.append(f"{hostname} ansible_host={ip} ansible_user={user}")
    inv_path = Path(tmpdir) / "inventory.ini"
    inv_path.write_text("\n".join(lines))
    return str(inv_path)


def _write_var_file(path: Path, vars_dict: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml.dump(vars_dict, default_flow_style=False, allow_unicode=True))


def _commit_var_files(var_files: list[Path]) -> None:
    """Commit changed var files to git. Silently skips if git is unavailable."""
    try:
        import git
        repo = git.Repo(_REPO_ROOT)
        for vf in var_files:
            repo.index.add([str(vf.relative_to(_REPO_ROOT))])
        if repo.index.diff("HEAD"):
            repo.index.commit(
                "chore(kri): update ansible var files",
                author=git.Actor("kri", "kri@localhost"),
                committer=git.Actor("kri", "kri@localhost"),
            )
    except Exception:
        pass  # non-fatal — var files are still written and used by ansible-runner


def _resolve_hosts(db, job: AnsibleJob, ssh_user: str) -> list[tuple[str, str, str]] | None:
    if job.target_type == "node":
        node = db.execute(
            select(Node).where(Node.id == _uuid.UUID(job.target_id))
        ).scalar_one_or_none()
        if not node or not node.ip_address:
            return None
        return [(node.hostname or node.minion_id, node.ip_address, ssh_user)]

    if job.target_type == "group":
        memberships = db.execute(
            select(GroupMembership).where(GroupMembership.group_id == _uuid.UUID(job.target_id))
        ).scalars().all()
        node_ids = [m.node_id for m in memberships]
        if not node_ids:
            return []
        nodes = db.execute(
            select(Node).where(Node.id.in_(node_ids), Node.ip_address.isnot(None))
        ).scalars().all()
        return [(n.hostname or n.minion_id, n.ip_address, ssh_user) for n in nodes]

    return None


@celery_app.task(
    name="fleet_platform.workers.playbook_tasks.run_playbook",
    bind=True,
    max_retries=0,
    queue="maintenance",
)
def run_playbook(self, job_id: str) -> dict:
    job_uuid = _uuid.UUID(job_id)

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
        if not job:
            return {"status": "error", "reason": "job_not_found"}
        job.status = "running"
        job.started_at = datetime.now(UTC)
        db.commit()
        _, ssh_user, ssh_password, _ = _get_bootstrap_settings(db)

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
        hosts = _resolve_hosts(db, job, ssh_user)

    if not hosts:
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
            job.status = "failed"
            job.stdout = "No hosts with IP addresses found for the selected target."
            job.completed_at = datetime.now(UTC)
            db.commit()
        return {"status": "error", "reason": "no_hosts"}

    # Write variable files and commit to git
    var_files: list[Path] = []
    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
        if job.extravars:
            if job.target_type == "node" and hosts:
                hostname = hosts[0][0]
                vf = _PLAYBOOKS_DIR / "host_vars" / f"{hostname}.yml"
                _write_var_file(vf, job.extravars)
                var_files.append(vf)
            elif job.target_type == "group":
                vf = _PLAYBOOKS_DIR / "group_vars" / f"{job.target_label}.yml"
                _write_var_file(vf, job.extravars)
                var_files.append(vf)

    if var_files:
        _commit_var_files(var_files)

    playbook_path = _PLAYBOOKS_DIR / job.playbook
    stdout_lines = []

    with tempfile.TemporaryDirectory(prefix="kri-playbook-") as tmpdir:
        inv_path = _write_static_inventory(tmpdir, hosts)
        result = ansible_runner.run(
            private_data_dir=tmpdir,
            playbook=str(playbook_path),
            inventory=inv_path,
            extravars=job.extravars or {},
            envvars={
                "ANSIBLE_USER": ssh_user,
                "ANSIBLE_PASSWORD": ssh_password,
            },
            quiet=False,
            rotate_artifacts=1,
        )
        for event in result.events:
            msg = event.get("stdout", "")
            if msg:
                stdout_lines.append(msg)

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
        job.status = "completed" if result.status == "successful" and result.rc == 0 else "failed"
        job.rc = result.rc
        job.stdout = "\n".join(stdout_lines) or f"rc={result.rc} status={result.status}"
        job.completed_at = datetime.now(UTC)
        db.commit()

    return {"status": result.status, "rc": result.rc, "job_id": job_id}
```

- [ ] **Step 5: Import in celery_app.py**

Read `fleet_platform/workers/celery_app.py`, then add alongside the existing task imports:
```python
from fleet_platform.workers import playbook_tasks  # noqa: F401
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_playbook_tasks.py -v 2>&1 | tail -8
```
Expected: `4 passed`

- [ ] **Step 7: Full test suite**

```bash
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/workers/playbook_tasks.py fleet_platform/workers/celery_app.py \
  pyproject.toml uv.lock tests/unit/test_playbook_tasks.py
git commit -m "feat(P12-T5): run_playbook task — static inventory + git commit vars"
```

---

## Task 6: Frontend — Playbooks page + Run modal with variable editor

**Files:**
- Create: `frontend/src/api/playbooks.ts`
- Create: `frontend/src/pages/PlaybooksPage.tsx`
- Create: `frontend/src/pages/PlaybookRunModal.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/Sidebar.tsx`

- [ ] **Step 1: Create playbooks API client**

```typescript
// frontend/src/api/playbooks.ts
import { api } from './client'

export interface PlaybookEntry {
  filename: string
  name: string
  description: string | null
  entry_type: 'playbook' | 'role'
  default_vars: Record<string, unknown>
}

export interface PlaybookRunResponse {
  job_id: string
  playbook: string
  target_label: string
  status: string
  message: string
}

export interface AnsibleJob {
  id: string
  playbook: string
  target_type: string
  target_label: string
  extravars: Record<string, unknown>
  status: 'pending' | 'running' | 'completed' | 'failed'
  triggered_by: string
  started_at: string | null
  completed_at: string | null
  stdout: string | null
  rc: number | null
  created_at: string
}

export const playbooksApi = {
  list: () => api.get<PlaybookEntry[]>('/api/v1/ansible/playbooks'),
  run: (playbook: string, target_type: string, target_id: string, extravars: Record<string, unknown>) =>
    api.post<PlaybookRunResponse>('/api/v1/ansible/playbooks/run', { playbook, target_type, target_id, extravars }),
  getJob: (jobId: string) => api.get<AnsibleJob>(`/api/v1/ansible/jobs/${jobId}`),
}
```

- [ ] **Step 2: Create PlaybookRunModal with variable editor**

```tsx
// frontend/src/pages/PlaybookRunModal.tsx
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { playbooksApi, PlaybookEntry } from '../api/playbooks'
import { fleetApi } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { useToastStore } from '../stores/toastStore'

interface Props {
  playbook: PlaybookEntry
  onClose: () => void
}

const STATUS_STYLE: Record<string, { label: string; colour: string }> = {
  pending:   { label: 'Queued',   colour: 'text-gray-500' },
  running:   { label: 'Running…', colour: 'text-brand-600' },
  completed: { label: 'Done ✓',   colour: 'text-emerald-700' },
  failed:    { label: 'Failed',   colour: 'text-red-700' },
}

export function PlaybookRunModal({ playbook, onClose }: Props) {
  const [targetType, setTargetType] = useState<'node' | 'group'>('node')
  const [targetId, setTargetId] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [vars, setVars] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(playbook.default_vars).map(([k, v]) => [k, String(v ?? '')])
    )
  )
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  const { data: nodes } = useQuery({
    queryKey: ['nodes-for-playbook'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    enabled: targetType === 'node',
    staleTime: 60_000,
  })

  const { data: groups } = useQuery({
    queryKey: ['groups-for-playbook'],
    queryFn: () => groupsApi.list({ per_page: 200 }),
    enabled: targetType === 'group',
    staleTime: 60_000,
  })

  const runMutation = useMutation({
    mutationFn: () => {
      // Coerce string values back to their original types where possible
      const extravars: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(vars)) {
        if (v === 'true') extravars[k] = true
        else if (v === 'false') extravars[k] = false
        else if (v !== '' && !isNaN(Number(v))) extravars[k] = Number(v)
        else extravars[k] = v
      }
      return playbooksApi.run(playbook.filename, targetType, targetId, extravars)
    },
    onSuccess: (data) => { setJobId(data.job_id); toast('Playbook queued') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const { data: jobData } = useQuery({
    queryKey: ['ansible-job', jobId],
    queryFn: () => playbooksApi.getJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return (s === 'pending' || s === 'running') ? 3000 : false
    },
  })

  useEffect(() => {
    if (jobData?.status === 'completed' || jobData?.status === 'failed') {
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    }
  }, [jobData?.status, qc])

  const status = jobData?.status
  const { label, colour } = STATUS_STYLE[status ?? 'pending'] ?? STATUS_STYLE.pending
  const hasVars = Object.keys(vars).length > 0

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-lg mx-4 flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Run Playbook</h2>
            <p className="text-sm text-gray-500">{playbook.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {!jobId ? (
          <form onSubmit={(e) => { e.preventDefault(); runMutation.mutate() }} className="space-y-5">
            {/* Target type */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Target type</label>
              <div className="flex gap-4">
                {(['node', 'group'] as const).map((t) => (
                  <label key={t} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="radio" name="targetType" value={t}
                      checked={targetType === t}
                      onChange={() => { setTargetType(t); setTargetId('') }}
                      className="accent-brand-600" />
                    {t === 'node' ? 'Single node' : 'Group'}
                  </label>
                ))}
              </div>
            </div>

            {/* Target selector */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {targetType === 'node' ? 'Node' : 'Group'}
              </label>
              <select required value={targetId} onChange={(e) => setTargetId(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600">
                <option value="">Select…</option>
                {targetType === 'node'
                  ? nodes?.items.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.hostname ?? n.minion_id} — {n.ip_address ?? 'no IP'}
                      </option>
                    ))
                  : groups?.items.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name} ({g.member_count} nodes)
                      </option>
                    ))
                }
              </select>
            </div>

            {/* Variable editor */}
            {hasVars && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Variables
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    (changes committed to git before run)
                  </span>
                </label>
                <div className="space-y-2 bg-gray-50 rounded-lg border border-gray-200 p-3">
                  {Object.entries(vars).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-xs font-mono text-gray-600 w-40 shrink-0">{key}</span>
                      <input
                        type="text"
                        value={value}
                        onChange={(e) => setVars((prev) => ({ ...prev, [key]: e.target.value }))}
                        className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:border-brand-600 font-mono"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-3 pt-1">
              <button type="button" onClick={onClose}
                className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button type="submit" disabled={!targetId || runMutation.isPending}
                className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                {runMutation.isPending ? 'Starting…' : 'Run Playbook'}
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
              <div className={`text-sm font-semibold ${colour}`}>{label}</div>
              <div className="text-sm text-gray-600 flex-1">{jobData?.target_label}</div>
              {(status === 'pending' || status === 'running') && (
                <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
              )}
            </div>

            {jobData?.stdout && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Output</p>
                <pre className="text-xs font-mono bg-gray-900 text-gray-100 rounded-lg p-3 overflow-x-auto max-h-64 whitespace-pre-wrap">
                  {jobData.stdout}
                </pre>
              </div>
            )}

            {typeof jobData?.rc === 'number' && (
              <p className="text-xs text-gray-400">Exit code: {jobData.rc}</p>
            )}

            <button onClick={onClose}
              className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
              {status === 'completed' || status === 'failed' ? 'Close' : 'Close (runs in background)'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create PlaybooksPage**

```tsx
// frontend/src/pages/PlaybooksPage.tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { playbooksApi, PlaybookEntry } from '../api/playbooks'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { PlaybookRunModal } from './PlaybookRunModal'

export function PlaybooksPage() {
  const [selected, setSelected] = useState<PlaybookEntry | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['playbooks'],
    queryFn: playbooksApi.list,
    staleTime: 60_000,
  })

  const playbooks = data?.filter((e) => e.entry_type === 'playbook') ?? []
  const roles = data?.filter((e) => e.entry_type === 'role') ?? []

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Playbooks</h1>
        <p className="text-gray-500 mt-1 text-sm">
          Run Ansible playbooks and roles from <code className="bg-gray-100 px-1 rounded text-xs">playbooks/</code>.
          Variable changes are committed to git before each run.
        </p>
      </div>

      {isLoading ? (
        <Skeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Failed to load playbooks" retry={refetch} />
      ) : (
        <>
          {/* Playbooks section */}
          {playbooks.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Playbooks</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {playbooks.map((p) => (
                  <PlaybookCard key={p.filename} entry={p} onRun={() => setSelected(p)} />
                ))}
              </div>
            </section>
          )}

          {/* Roles section */}
          {roles.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Roles</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {roles.map((r) => (
                  <PlaybookCard key={r.filename} entry={r} onRun={() => setSelected(r)} />
                ))}
              </div>
            </section>
          )}

          {playbooks.length === 0 && roles.length === 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400 text-sm">
              No <code>.yml</code> files or roles found in <code>playbooks/</code>.
            </div>
          )}
        </>
      )}

      {selected && <PlaybookRunModal playbook={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function PlaybookCard({ entry, onRun }: { entry: PlaybookEntry; onRun: () => void }) {
  const varCount = Object.keys(entry.default_vars).length
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 flex flex-col gap-3 hover:border-brand-300 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-gray-900 text-sm">{entry.name}</p>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{entry.filename}</p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded font-medium flex-shrink-0 ${
          entry.entry_type === 'role'
            ? 'bg-purple-100 text-purple-700 border border-purple-200'
            : 'bg-brand-50 text-brand-700 border border-brand-200'
        }`}>
          {entry.entry_type}
        </span>
      </div>

      {entry.description && (
        <p className="text-sm text-gray-600 flex-1">{entry.description}</p>
      )}

      {varCount > 0 && (
        <div className="bg-gray-50 rounded-lg border border-gray-100 p-2.5 space-y-1">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Variables ({varCount})</p>
          {Object.entries(entry.default_vars).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 text-xs">
              <span className="font-mono text-gray-600 w-36 truncate">{k}</span>
              <span className="font-mono text-gray-400 truncate">{String(v)}</span>
            </div>
          ))}
        </div>
      )}

      <button
        onClick={onRun}
        className="mt-auto px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
      >
        Run
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Add Ansible endpoint section to SettingsPage.tsx**

In `frontend/src/pages/SettingsPage.tsx`, read the file and add after the SSH credentials section:

```tsx
      {/* External Ansible endpoint */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-900">External Ansible Endpoint</h2>
        <p className="text-sm text-gray-500">
          Optional: configure an AWX or Ansible Tower endpoint. When set, kri will POST playbook jobs
          to this endpoint instead of running ansible-runner locally.
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Endpoint URL</label>
          <input type="text" value={ansibleEndpoint} onChange={(e) => setAnsibleEndpoint(e.target.value)}
            placeholder="https://awx.example.com"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
          <p className="text-xs text-gray-400 mt-1">Leave blank to use local ansible-runner.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            API Token
            <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted)</span>
          </label>
          <input type="password" value={ansibleToken} onChange={(e) => setAnsibleToken(e.target.value)}
            placeholder="Leave blank to keep existing"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
        </div>
      </div>
```

Also add state variables near the top of `SettingsPage`:
```tsx
const [ansibleEndpoint, setAnsibleEndpoint] = useState('')
const [ansibleToken, setAnsibleToken] = useState('')
```

Update the `useEffect` to also seed `ansibleEndpoint` from `data`:
```tsx
if (data?.ansible_endpoint_url) setAnsibleEndpoint(data.ansible_endpoint_url)
```

Update `saveMutation.mutationFn` to include new fields:
```tsx
mutationFn: () => ansibleApi.updateSettings({
  salt_master_address: master || undefined,
  ssh_bootstrap_username: username || undefined,
  ssh_bootstrap_password: password || undefined,
  ansible_endpoint_url: ansibleEndpoint || undefined,
  ansible_api_token: ansibleToken || undefined,
}),
```

Also update the `ansibleApi.updateSettings` type in `frontend/src/api/ansible.ts`:
```typescript
updateSettings: (payload: {
  salt_master_address?: string
  ssh_bootstrap_username?: string
  ssh_bootstrap_password?: string
  ansible_endpoint_url?: string
  ansible_api_token?: string
}) => api.put<PlatformSettings>('/api/v1/settings', payload),
```

And extend `PlatformSettings` interface:
```typescript
export interface PlatformSettings {
  salt_master_address: string | null
  ssh_bootstrap_username: string | null
  ssh_bootstrap_password: null
  controller_pubkey: string | null
  ansible_endpoint_url: string | null
}
```

- [ ] **Step 5: Wire up App.tsx and Sidebar.tsx**

In `frontend/src/App.tsx`, add:
```tsx
import { PlaybooksPage } from './pages/PlaybooksPage'
// inside Routes:
<Route path="/playbooks" element={<PlaybooksPage />} />
```

In `frontend/src/components/Layout/Sidebar.tsx`, add to `links` after Executions:
```tsx
{ to: '/playbooks', label: 'Playbooks', icon: '▤' },
```

- [ ] **Step 6: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: zero errors.

- [ ] **Step 7: Production build**

```bash
npm run build 2>&1 | grep -E "built|error" | head -3
```
Expected: `✓ built`

- [ ] **Step 8: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/api/playbooks.ts frontend/src/api/ansible.ts \
  frontend/src/pages/PlaybooksPage.tsx frontend/src/pages/PlaybookRunModal.tsx \
  frontend/src/pages/SettingsPage.tsx frontend/src/App.tsx \
  frontend/src/components/Layout/Sidebar.tsx
git commit -m "feat(P12-T6): Playbooks page with variable editor + Ansible endpoint settings"
```

---

## Task 7: Final test sweep + merge

- [ ] **Step 1: Run full backend test suite**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: all pass (190+ tests).

- [ ] **Step 2: Production build**

```bash
cd /home/dk/Documents/git/kri/frontend && npm run build 2>&1 | grep -E "built|error"
```
Expected: `✓ built`

- [ ] **Step 3: Merge Plan 11 branch first, then Plan 12 work**

```bash
cd /home/dk/Documents/git/kri
git checkout master
git merge feat/plan-11-ansible-bootstrap --no-ff -m "feat: Plan 11 — Ansible bootstrap integration"
# Plan 12 work is on the same branch; if on a separate branch, merge it too
```

---

## Checklist

- [x] Playbook discovery (`playbooks/*.yml`) with name, description, vars — Task 1
- [x] Role discovery (`playbooks/roles/*/`) with defaults from `defaults/main.yml` — Task 1
- [x] Playbooks and roles shown in separate sections with variable cards — Task 6
- [x] Editable variable form before run, values pre-filled from defaults — Task 6
- [x] Variable overrides written to `host_vars/` or `group_vars/` and git-committed — Task 5
- [x] Target selector: single node or group — Task 4 + Task 6
- [x] Group target resolves all member IPs automatically — Task 5
- [x] `AnsibleJob` DB model with `extravars` JSONB — Task 2
- [x] List playbooks endpoint (`GET /api/v1/ansible/playbooks`) — Task 4
- [x] Run playbook endpoint (`POST /api/v1/ansible/playbooks/run`) — Task 4
- [x] Job status endpoint (`GET /api/v1/ansible/jobs/{job_id}`) — Task 4
- [x] Path traversal protection — Task 4
- [x] External Ansible endpoint URL + token in platform settings — Task 3 + Task 6
- [x] Live polling in run modal (3 s interval until done) — Task 6
- [x] stdout output displayed in run modal — Task 6
- [x] Sidebar + routing — Task 6
