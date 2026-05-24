# Fleet Platform — Plan 4: Drift Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the drift detection engine — baselines define desired state, the engine diffs actual grains against them, scores the result, persists it to the TimescaleDB hypertable, and exposes the data through drift, baseline, and execution-history API endpoints.

**Architecture:** `DriftEngine` is a pure stateless service (no DB, no Celery) that takes a grains dict and a baseline dict and returns a `DriftResult` dataclass — fully unit-testable without infrastructure. The `compute_drift` Celery task (already a stub from Plan 2) is replaced with the real implementation that calls the engine, writes a `DriftRecord`, and updates `nodes.drift_score`. Baselines are stored as JSONB in `desired_state_baselines`; a `BaselineLoader` converts YAML files to DB rows. Three new API routers expose drift timelines, fleet-wide rankings, and execution history.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0, Celery 5.4, pyyaml 6, pydantic v2, pytest 8.3, pytest-asyncio 1.3

**Branch:** `feat/plan-4-drift-engine` (branch from `master` before starting)

---

## Scope

This is Plan 4 of 6:
- ✅ Plan 1: Foundation
- ✅ Plan 2: Salt + ingest pipeline
- ✅ Plan 3: Fleet API
- **Plan 4 (this):** Drift engine + baselines + execution history
- Plan 5: SBOM pipeline
- Plan 6: React frontend

When Plan 4 is complete: any node with facts and a baseline gets an accurate drift score; operators can trigger recomputes; the frontend (Plan 6) has all the drift + execution history data it needs.

---

## File Map

```
fleet_platform/
├── services/
│   ├── drift_engine.py         CREATE — pure compute_drift(grains, baseline) → DriftResult
│   └── baseline_loader.py      CREATE — find_baseline_for_node(), store_baseline()
├── workers/
│   └── drift_tasks.py          MODIFY — replace stub with real implementation
├── schemas/
│   ├── drift.py                CREATE — DriftRecordResponse, BaselineCreate/Response
│   └── execution.py            CREATE — ExecutionJobResponse, ExecutionResultResponse
└── api/
    ├── main.py                 MODIFY — register drift, baselines, executions routers
    └── routes/
        ├── drift.py            CREATE — /api/v1/drift (fleet list + per-node + trigger)
        ├── baselines.py        CREATE — /api/v1/baselines CRUD
        └── executions.py       CREATE — /api/v1/executions list + detail

baselines/
├── global.yaml                 CREATE — global baseline (applied to all nodes)
└── roles/
    └── builder.yaml            CREATE — role-specific baseline example

tests/
├── unit/
│   ├── test_drift_engine.py    CREATE — 12 pure unit tests for drift computation
│   └── test_baseline_loader.py CREATE — 5 tests for YAML loading + validation
└── integration/
    ├── test_drift_api.py        CREATE — 7 tests
    ├── test_baselines_api.py   CREATE — 6 tests
    └── test_executions_api.py  CREATE — 5 tests
```

---

## Task 1: Drift schemas + execution schemas

**Files:**
- Create: `fleet_platform/schemas/drift.py`
- Create: `fleet_platform/schemas/execution.py`
- Create: `tests/unit/test_drift_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_drift_schemas.py
import uuid
from datetime import UTC, datetime

import pytest
from fleet_platform.schemas.drift import (
    DriftRecordResponse, BaselineCreate, BaselineResponse, drift_severity,
)
from fleet_platform.schemas.execution import ExecutionJobResponse


def test_drift_severity_clean():
    assert drift_severity(0) == "clean"
    assert drift_severity(5) == "clean"


def test_drift_severity_low():
    assert drift_severity(6) == "low"
    assert drift_severity(20) == "low"


def test_drift_severity_medium():
    assert drift_severity(21) == "medium"
    assert drift_severity(50) == "medium"


def test_drift_severity_high():
    assert drift_severity(51) == "high"
    assert drift_severity(80) == "high"


def test_drift_severity_critical():
    assert drift_severity(81) == "critical"
    assert drift_severity(100) == "critical"


def test_baseline_create_defaults():
    b = BaselineCreate(
        name="global",
        state_json={"packages": {"required": []}},
    )
    assert b.target_type == "global"
    assert b.git_commit_sha == "manual"


def test_execution_job_response():
    j = ExecutionJobResponse(
        id=uuid.uuid4(), type="highstate", target_type="node",
        triggered_by="salt", status="complete",
    )
    assert j.status == "complete"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
pytest tests/unit/test_drift_schemas.py -v
```

- [ ] **Step 3: Create fleet_platform/schemas/drift.py**

```python
# fleet_platform/schemas/drift.py
import uuid
from datetime import datetime

from pydantic import BaseModel


def drift_severity(score: int) -> str:
    """Map a 0–100 drift score to a severity label."""
    if score <= 5:
        return "clean"
    if score <= 20:
        return "low"
    if score <= 50:
        return "medium"
    if score <= 80:
        return "high"
    return "critical"


class DriftSummaryResponse(BaseModel):
    node_id: uuid.UUID
    hostname: str | None
    drift_score: int
    severity: str
    computed_at: datetime | None
    baseline_name: str | None


class DriftRecordResponse(BaseModel):
    node_id: uuid.UUID
    baseline_id: uuid.UUID | None
    baseline_name: str | None
    computed_at: datetime
    drift_score: int
    severity: str
    missing_packages: list[dict]
    extra_packages: list[dict]
    version_mismatches: list[dict]
    service_drift: list[dict]
    config_drift: list[dict]

    model_config = {"from_attributes": True}


class BaselineCreate(BaseModel):
    name: str
    description: str | None = None
    target_type: str = "global"   # global | group | node
    target_id: uuid.UUID | None = None
    state_json: dict
    git_commit_sha: str = "manual"


class BaselineResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    target_type: str
    target_id: uuid.UUID | None
    git_commit_sha: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Create fleet_platform/schemas/execution.py**

```python
# fleet_platform/schemas/execution.py
import uuid
from datetime import datetime

from pydantic import BaseModel


class ExecutionJobResponse(BaseModel):
    id: uuid.UUID
    salt_jid: str | None = None
    type: str
    target_type: str
    target_id: uuid.UUID | None = None
    triggered_by: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ExecutionResultResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    node_id: uuid.UUID
    status: str
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    completed_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Run — expect 7 passed**

```bash
source .venv/bin/activate && pytest tests/unit/test_drift_schemas.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/schemas/drift.py fleet_platform/schemas/execution.py \
        tests/unit/test_drift_schemas.py
git commit -m "feat: drift + execution schemas with drift_severity() helper"
```

---

## Task 2: DriftEngine service

**Files:**
- Create: `fleet_platform/services/drift_engine.py`
- Create: `tests/unit/test_drift_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_drift_engine.py
import pytest
from fleet_platform.services.drift_engine import compute_drift, DriftResult


_GRAINS_FULL = {
    "pkgs": {
        "git": "2.43.0",
        "python3": "3.12.2",
        "teamviewer": "15.51.0",   # forbidden package
    },
    "services": ["com.apple.screensharing"],  # should be stopped
}

_BASELINE_FULL = {
    "packages": {
        "required": [
            {"name": "git", "version": ">=2.39.0"},
            {"name": "python3"},
            {"name": "node"},  # missing
        ],
        "forbidden": [
            {"name": "teamviewer"},
        ],
    },
    "services": {
        "required_stopped": ["com.apple.screensharing"],
    },
}


def test_compute_drift_returns_result():
    result = compute_drift({}, {})
    assert isinstance(result, DriftResult)


def test_clean_node_scores_zero():
    result = compute_drift(
        {"pkgs": {"git": "2.43.0"}},
        {"packages": {"required": [{"name": "git"}]}},
    )
    assert result.drift_score == 0
    assert result.missing_packages == []


def test_missing_required_package_detected():
    result = compute_drift(
        {"pkgs": {"git": "2.43.0"}},
        {"packages": {"required": [{"name": "git"}, {"name": "node"}]}},
    )
    assert len(result.missing_packages) == 1
    assert result.missing_packages[0]["name"] == "node"


def test_missing_package_adds_20_to_score():
    result = compute_drift(
        {},
        {"packages": {"required": [{"name": "git"}]}},
    )
    assert result.drift_score == 20


def test_forbidden_package_detected():
    result = compute_drift(
        {"pkgs": {"teamviewer": "15.0"}},
        {"packages": {"forbidden": [{"name": "teamviewer"}]}},
    )
    assert len(result.extra_packages) == 1
    assert result.extra_packages[0]["name"] == "teamviewer"


def test_forbidden_package_adds_10_to_score():
    result = compute_drift(
        {"pkgs": {"teamviewer": "15.0"}},
        {"packages": {"forbidden": [{"name": "teamviewer"}]}},
    )
    assert result.drift_score == 10


def test_version_mismatch_detected():
    result = compute_drift(
        {"pkgs": {"git": "2.30.0"}},
        {"packages": {"required": [{"name": "git", "version": ">=2.39.0"}]}},
    )
    assert len(result.version_mismatches) == 1
    assert result.version_mismatches[0]["name"] == "git"


def test_version_major_mismatch_severity():
    result = compute_drift(
        {"pkgs": {"python3": "2.7.0"}},
        {"packages": {"required": [{"name": "python3", "version": ">=3.11.0"}]}},
    )
    assert result.version_mismatches[0]["severity"] == "major"


def test_service_drift_detected():
    result = compute_drift(
        {"pkgs": {}, "services": ["com.apple.screensharing"]},
        {"services": {"required_stopped": ["com.apple.screensharing"]}},
    )
    assert len(result.service_drift) == 1
    assert result.service_drift[0]["expected"] == "stopped"


def test_score_capped_at_100():
    # 10 missing packages × 20 = 200 → capped at 100
    many_missing = [{"name": f"pkg{i}"} for i in range(10)]
    result = compute_drift(
        {},
        {"packages": {"required": many_missing}},
    )
    assert result.drift_score == 100


def test_case_insensitive_package_matching():
    result = compute_drift(
        {"pkgs": {"Git": "2.43.0"}},
        {"packages": {"required": [{"name": "git"}]}},
    )
    assert result.missing_packages == []


def test_full_baseline_composite_score():
    result = compute_drift(_GRAINS_FULL, _BASELINE_FULL)
    assert result.drift_score > 0
    assert len(result.missing_packages) == 1   # node missing
    assert len(result.extra_packages) == 1     # teamviewer present
    assert len(result.service_drift) == 1      # screensharing running
```

- [ ] **Step 2: Run — expect ImportError**

```bash
source .venv/bin/activate && pytest tests/unit/test_drift_engine.py -v
```

- [ ] **Step 3: Create fleet_platform/services/drift_engine.py**

```python
# fleet_platform/services/drift_engine.py
"""Pure stateless drift computation. No DB, no Celery — fully unit-testable."""
import re
from dataclasses import dataclass, field

# Scoring weights per violation type
_WEIGHTS = {
    "missing_required_package": 20,
    "extra_forbidden_package": 10,
    "version_mismatch_major": 15,
    "version_mismatch_minor": 5,
    "service_drift": 15,
}


@dataclass
class DriftResult:
    drift_score: int = 0
    missing_packages: list[dict] = field(default_factory=list)
    extra_packages: list[dict] = field(default_factory=list)
    version_mismatches: list[dict] = field(default_factory=list)
    service_drift: list[dict] = field(default_factory=list)
    config_drift: list[dict] = field(default_factory=list)


def compute_drift(grains: dict, baseline: dict) -> DriftResult:
    """Compute drift between actual grains and desired baseline spec.

    Args:
        grains: Salt grain dict from the node (e.g. NodeFact.grains).
        baseline: Desired state dict (e.g. DesiredStateBaseline.state_json).

    Returns:
        DriftResult with score 0–100 and per-category diff lists.
    """
    missing = _check_missing(grains, baseline)
    extra = _check_extra(grains, baseline)
    version_mismatches = _check_versions(grains, baseline)
    services = _check_services(grains, baseline)

    score = (
        len(missing) * _WEIGHTS["missing_required_package"]
        + len(extra) * _WEIGHTS["extra_forbidden_package"]
        + sum(
            _WEIGHTS[f"version_mismatch_{v['severity']}"]
            for v in version_mismatches
        )
        + len(services) * _WEIGHTS["service_drift"]
    )

    return DriftResult(
        drift_score=min(100, score),
        missing_packages=missing,
        extra_packages=extra,
        version_mismatches=version_mismatches,
        service_drift=services,
        config_drift=[],  # requires config file facts — deferred
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _installed(grains: dict) -> dict[str, str]:
    """Return {lowercase_name: version} from grains."""
    pkgs = grains.get("pkgs") or grains.get("brew_pkgs") or {}
    if not isinstance(pkgs, dict):
        return {}
    return {k.lower(): str(v) for k, v in pkgs.items()}


def _check_missing(grains: dict, baseline: dict) -> list[dict]:
    installed = _installed(grains)
    required = baseline.get("packages", {}).get("required", [])
    return [
        {"name": pkg["name"], "required_version": pkg.get("version")}
        for pkg in required
        if pkg["name"].lower() not in installed
    ]


def _check_extra(grains: dict, baseline: dict) -> list[dict]:
    installed = _installed(grains)
    forbidden = baseline.get("packages", {}).get("forbidden", [])
    return [
        {"name": pkg["name"], "installed_version": installed[pkg["name"].lower()]}
        for pkg in forbidden
        if pkg["name"].lower() in installed
    ]


def _parse_version(v: str) -> tuple[int, ...]:
    """Return a comparable version tuple from a version string."""
    digits = re.findall(r"\d+", re.sub(r"^[>=<~^]+", "", v))
    return tuple(int(d) for d in digits[:3]) if digits else (0,)


def _check_versions(grains: dict, baseline: dict) -> list[dict]:
    installed = _installed(grains)
    required = baseline.get("packages", {}).get("required", [])
    mismatches = []
    for pkg in required:
        name = pkg["name"].lower()
        constraint = pkg.get("version")
        if not constraint or name not in installed:
            continue
        actual_v = _parse_version(installed[name])
        required_v = _parse_version(constraint)
        if ">=" in constraint and actual_v < required_v:
            severity = "major" if (actual_v[0] if actual_v else 0) < (required_v[0] if required_v else 0) else "minor"
            mismatches.append({
                "name": pkg["name"],
                "actual": installed[name],
                "required": constraint,
                "severity": severity,
            })
    return mismatches


def _check_services(grains: dict, baseline: dict) -> list[dict]:
    running = set(grains.get("services") or [])
    spec = baseline.get("services", {})
    drift = []
    for svc in spec.get("required_stopped", []):
        if svc in running:
            drift.append({"service": svc, "expected": "stopped", "actual": "running"})
    for svc in spec.get("required_running", []):
        if svc not in running:
            drift.append({"service": svc, "expected": "running", "actual": "stopped"})
    return drift
```

- [ ] **Step 4: Run — expect 12 passed**

```bash
source .venv/bin/activate && pytest tests/unit/test_drift_engine.py -v
```

Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/drift_engine.py tests/unit/test_drift_engine.py
git commit -m "feat: DriftEngine service — pure compute_drift() with scoring, 12 unit tests"
```

---

## Task 3: BaselineLoader + sample baselines

**Files:**
- Create: `fleet_platform/services/baseline_loader.py`
- Create: `baselines/global.yaml`
- Create: `baselines/roles/builder.yaml`
- Create: `tests/unit/test_baseline_loader.py`

- [ ] **Step 1: Add pyyaml to pyproject.toml**

In `pyproject.toml`, add `"pyyaml>=6.0"` to the `dependencies` list. Then:

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate && uv sync
```

- [ ] **Step 2: Write failing tests**

```python
# tests/unit/test_baseline_loader.py
import pytest
from pathlib import Path

from fleet_platform.services.baseline_loader import (
    load_baseline_yaml,
    validate_baseline,
)


def test_load_baseline_yaml_from_file(tmp_path):
    yml = tmp_path / "test.yaml"
    yml.write_text("name: test\npackages:\n  required:\n    - name: git\n")
    data = load_baseline_yaml(str(yml))
    assert data["name"] == "test"
    assert data["packages"]["required"][0]["name"] == "git"


def test_validate_baseline_valid():
    errors = validate_baseline({"name": "global", "packages": {"required": []}})
    assert errors == []


def test_validate_baseline_missing_name():
    errors = validate_baseline({"packages": {"required": []}})
    assert any("name" in e for e in errors)


def test_validate_baseline_no_sections():
    errors = validate_baseline({"name": "empty"})
    assert any("packages" in e or "services" in e for e in errors)


def test_validate_baseline_invalid_target_type():
    errors = validate_baseline({
        "name": "x",
        "target_type": "invalid",
        "packages": {"required": []},
    })
    assert any("target_type" in e for e in errors)
```

- [ ] **Step 3: Run — expect ImportError**

```bash
source .venv/bin/activate && pytest tests/unit/test_baseline_loader.py -v
```

- [ ] **Step 4: Create fleet_platform/services/baseline_loader.py**

```python
# fleet_platform/services/baseline_loader.py
"""Load baseline YAML files and find applicable baselines for nodes."""
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from fleet_platform.models.drift import DesiredStateBaseline
from fleet_platform.models.group import GroupMember

_VALID_TARGET_TYPES = {"global", "group", "node"}


def load_baseline_yaml(path: str | Path) -> dict:
    """Parse a YAML baseline file. Returns the dict."""
    with open(path) as f:
        return yaml.safe_load(f)


def validate_baseline(data: dict) -> list[str]:
    """Return a list of validation error strings. Empty = valid."""
    errors = []
    if "name" not in data:
        errors.append("missing required field: name")
    target_type = data.get("target_type", "global")
    if target_type not in _VALID_TARGET_TYPES:
        errors.append(f"target_type must be one of {sorted(_VALID_TARGET_TYPES)}, got '{target_type}'")
    has_content = any(k in data for k in ("packages", "services", "configs"))
    if not has_content:
        errors.append("baseline must define at least one of: packages, services, configs")
    return errors


async def find_baseline_for_node(
    node_id: uuid.UUID, db: AsyncSession
) -> DesiredStateBaseline | None:
    """Return the most specific applicable baseline for a node.

    Priority: node-specific > group-specific > global
    """
    # 1. Node-specific baseline
    result = await db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "node")
        .where(DesiredStateBaseline.target_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    )
    if baseline := result.scalar_one_or_none():
        return baseline

    # 2. Group-specific (any group the node belongs to)
    result = await db.execute(
        select(DesiredStateBaseline)
        .join(GroupMember, GroupMember.group_id == DesiredStateBaseline.target_id)
        .where(DesiredStateBaseline.target_type == "group")
        .where(GroupMember.node_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    )
    if baseline := result.scalar_one_or_none():
        return baseline

    # 3. Global baseline
    result = await db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "global")
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def find_baseline_for_node_sync(
    node_id: uuid.UUID, db: Session
) -> DesiredStateBaseline | None:
    """Sync version of find_baseline_for_node for use in Celery workers."""
    baseline = db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "node")
        .where(DesiredStateBaseline.target_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baseline:
        return baseline

    baseline = db.execute(
        select(DesiredStateBaseline)
        .join(GroupMember, GroupMember.group_id == DesiredStateBaseline.target_id)
        .where(DesiredStateBaseline.target_type == "group")
        .where(GroupMember.node_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baseline:
        return baseline

    return db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "global")
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
```

- [ ] **Step 5: Create baselines/global.yaml**

```bash
mkdir -p baselines/roles
```

```yaml
# baselines/global.yaml
name: global
description: "Baseline applied to all managed Mac Minis"
target_type: global
version: "1.0"

packages:
  required:
    - name: git
      version: ">=2.39.0"
    - name: python3
      version: ">=3.11.0"
  forbidden:
    - name: teamviewer
    - name: anydesk

services:
  required_stopped:
    - com.apple.screensharing
    - com.apple.ARDAgent
```

- [ ] **Step 6: Create baselines/roles/builder.yaml**

```yaml
# baselines/roles/builder.yaml
name: builder
description: "Baseline for CI builder Mac Minis"
target_type: global
version: "1.0"

packages:
  required:
    - name: git
      version: ">=2.39.0"
    - name: python3
      version: ">=3.11.0"
    - name: node
      version: ">=20.0.0"
    - name: docker
  forbidden:
    - name: teamviewer
    - name: anydesk
    - name: vlc

services:
  required_stopped:
    - com.apple.screensharing
    - com.apple.ARDAgent
  required_running:
    - com.docker.helper
```

- [ ] **Step 7: Run tests — expect 5 passed**

```bash
source .venv/bin/activate && pytest tests/unit/test_baseline_loader.py -v
```

Expected: `5 passed`

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/services/baseline_loader.py \
        tests/unit/test_baseline_loader.py \
        baselines/ pyproject.toml uv.lock
git commit -m "feat: BaselineLoader — load/validate YAML, find_baseline_for_node(), sample baselines"
```

---

## Task 4: Implement compute_drift Celery task

**Files:**
- Modify: `fleet_platform/workers/drift_tasks.py`
- Create: `tests/unit/test_drift_task.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_drift_task.py
from unittest.mock import MagicMock, patch
import uuid


def _make_mock_db():
    """Return a mock sync DB session."""
    db = MagicMock()
    db.__enter__ = lambda s: s
    db.__exit__ = MagicMock(return_value=False)
    return db


def test_compute_drift_no_facts_returns_no_facts_status():
    from fleet_platform.workers.drift_tasks import compute_drift

    mock_db = _make_mock_db()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None  # no NodeFact

    with patch("fleet_platform.workers.drift_tasks.get_sync_db", return_value=mock_db):
        result = compute_drift(str(uuid.uuid4()))

    assert result["status"] == "no_facts"


def test_compute_drift_no_baseline_returns_no_baseline_status():
    from fleet_platform.workers.drift_tasks import compute_drift
    from unittest.mock import MagicMock

    node_id = str(uuid.uuid4())
    mock_fact = MagicMock()
    mock_fact.grains = {"pkgs": {"git": "2.43.0"}}

    mock_db = _make_mock_db()
    # First execute → NodeFact found; subsequent → no baseline
    execute_results = [
        MagicMock(**{"scalar_one_or_none.return_value": mock_fact}),  # NodeFact
        MagicMock(**{"scalar_one_or_none.return_value": None}),       # node baseline
        MagicMock(**{"scalar_one_or_none.return_value": None}),       # group baseline
        MagicMock(**{"scalar_one_or_none.return_value": None}),       # global baseline
    ]
    mock_db.execute.side_effect = execute_results

    with patch("fleet_platform.workers.drift_tasks.get_sync_db", return_value=mock_db):
        result = compute_drift(node_id)

    assert result["status"] == "no_baseline"


def test_compute_drift_writes_drift_record_and_returns_score():
    from fleet_platform.workers.drift_tasks import compute_drift
    from unittest.mock import MagicMock, call

    node_id = str(uuid.uuid4())
    mock_fact = MagicMock()
    mock_fact.grains = {"pkgs": {"git": "2.43.0"}}

    mock_baseline = MagicMock()
    mock_baseline.id = uuid.uuid4()
    mock_baseline.state_json = {"packages": {"required": [{"name": "git"}]}}

    mock_node = MagicMock()
    mock_node.id = uuid.UUID(node_id)
    mock_node.drift_score = 0

    mock_db = _make_mock_db()
    execute_results = [
        MagicMock(**{"scalar_one_or_none.return_value": mock_fact}),       # NodeFact
        MagicMock(**{"scalar_one_or_none.return_value": None}),            # node baseline
        MagicMock(**{"scalar_one_or_none.return_value": None}),            # group baseline
        MagicMock(**{"scalar_one_or_none.return_value": mock_baseline}),   # global baseline
        MagicMock(**{"scalar_one_or_none.return_value": mock_node}),       # Node update
    ]
    mock_db.execute.side_effect = execute_results

    with patch("fleet_platform.workers.drift_tasks.get_sync_db", return_value=mock_db):
        result = compute_drift(node_id)

    assert result["status"] == "computed"
    assert "drift_score" in result
    assert result["drift_score"] == 0  # git is installed, no drift
    mock_db.add.assert_called()   # DriftRecord was added
    mock_db.commit.assert_called()
```

- [ ] **Step 2: Run — expect failures (stub returns "queued")**

```bash
source .venv/bin/activate && pytest tests/unit/test_drift_task.py -v
```

- [ ] **Step 3: Replace fleet_platform/workers/drift_tasks.py**

```python
# fleet_platform/workers/drift_tasks.py
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.group import GroupMember
from fleet_platform.models.node import Node
from fleet_platform.services.baseline_loader import find_baseline_for_node_sync
from fleet_platform.services.drift_engine import compute_drift as engine_compute_drift
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.drift_tasks.compute_drift",
    bind=True,
    max_retries=3,
    queue="drift",
)
def compute_drift(self, node_id: str) -> dict:
    """Compute drift for a node and persist the result."""
    node_uuid = uuid.UUID(node_id)

    with get_sync_db() as db:
        # 1. Get latest grain facts
        fact = db.execute(
            select(NodeFact)
            .where(NodeFact.node_id == node_uuid)
            .order_by(NodeFact.collected_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not fact:
            return {"node_id": node_id, "status": "no_facts"}

        # 2. Find applicable baseline
        baseline = find_baseline_for_node_sync(node_uuid, db)
        if not baseline:
            return {"node_id": node_id, "status": "no_baseline"}

        # 3. Compute drift (pure function — no DB)
        result = engine_compute_drift(fact.grains, baseline.state_json)
        now = datetime.now(UTC)

        # 4. Persist drift record
        db.add(DriftRecord(
            node_id=node_uuid,
            baseline_id=baseline.id,
            computed_at=now,
            drift_score=result.drift_score,
            missing_packages=result.missing_packages,
            extra_packages=result.extra_packages,
            version_mismatches=result.version_mismatches,
            service_drift=result.service_drift,
            config_drift=result.config_drift,
        ))

        # 5. Update nodes.drift_score
        node = db.execute(
            select(Node).where(Node.id == node_uuid)
        ).scalar_one_or_none()
        if node:
            node.drift_score = result.drift_score

        db.commit()

    return {
        "node_id": node_id,
        "status": "computed",
        "drift_score": result.drift_score,
    }
```

- [ ] **Step 4: Run — expect 3 passed**

```bash
source .venv/bin/activate && pytest tests/unit/test_drift_task.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/workers/drift_tasks.py tests/unit/test_drift_task.py
git commit -m "feat: implement compute_drift Celery task — replaces Plan 2 stub"
```

---

## Task 5: Baselines API

**Files:**
- Create: `fleet_platform/api/routes/baselines.py`
- Create: `tests/integration/test_baselines_api.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_baselines_api.py
import pytest
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
```

- [ ] **Step 2: Run — expect 404/401**

```bash
source .venv/bin/activate && pytest tests/integration/test_baselines_api.py -v
```

- [ ] **Step 3: Create fleet_platform/api/routes/baselines.py**

```python
# fleet_platform/api/routes/baselines.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.drift import DesiredStateBaseline
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.drift import BaselineCreate, BaselineResponse

router = APIRouter(prefix="/api/v1/baselines")


@router.get("", response_model=PaginatedResponse[BaselineResponse])
async def list_baselines(
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(DesiredStateBaseline))).scalar_one()
    result = await db.execute(
        select(DesiredStateBaseline)
        .order_by(DesiredStateBaseline.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    baselines = result.scalars().all()
    return PaginatedResponse(
        items=[BaselineResponse.model_validate(b) for b in baselines],
        total=total, page=page, per_page=per_page,
    )


@router.post("", response_model=BaselineResponse, status_code=201)
async def create_baseline(
    payload: BaselineCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    baseline = DesiredStateBaseline(
        name=payload.name,
        description=payload.description,
        target_type=payload.target_type,
        target_id=payload.target_id,
        git_commit_sha=payload.git_commit_sha,
        state_json=payload.state_json,
    )
    db.add(baseline)
    await db.commit()
    await db.refresh(baseline)
    return BaselineResponse.model_validate(baseline)


@router.get("/{baseline_id}", response_model=BaselineResponse)
async def get_baseline(
    baseline_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(DesiredStateBaseline).where(DesiredStateBaseline.id == baseline_id)
    )
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
    return BaselineResponse.model_validate(baseline)
```

- [ ] **Step 4: Register in fleet_platform/api/main.py**

Add `baselines` to the import and `app.include_router(baselines.router, tags=["baselines"])` after the groups router.

In `fleet_platform/api/main.py`, change:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet, groups, search
```
to:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet, groups, search, baselines
```

Add after `app.include_router(search.router, tags=["search"])`:
```python
app.include_router(baselines.router, tags=["baselines"])
```

- [ ] **Step 5: Run — expect 6 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_baselines_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/baselines.py fleet_platform/api/main.py \
        tests/integration/test_baselines_api.py
git commit -m "feat: baselines API — GET/POST /api/v1/baselines, GET /api/v1/baselines/{id}"
```

---

## Task 6: Drift API routes

**Files:**
- Create: `fleet_platform/api/routes/drift.py`
- Create: `tests/integration/test_drift_api.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_drift_api.py
import secrets
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.node import Node


@pytest.fixture
async def node_with_drift(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="drift-test-01.local", hostname="drift-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC), status="online", drift_score=45,
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    baseline = DesiredStateBaseline(
        name="drift-test-baseline",
        target_type="global",
        git_commit_sha="abc1234",
        state_json={"packages": {"required": [{"name": "git"}]}},
    )
    db_session.add(baseline)
    await db_session.commit()
    await db_session.refresh(baseline)

    record = DriftRecord(
        node_id=node.id,
        baseline_id=baseline.id,
        computed_at=datetime.now(UTC),
        drift_score=45,
        missing_packages=[{"name": "node", "required_version": None}],
        extra_packages=[{"name": "teamviewer", "installed_version": "15.0"}],
        version_mismatches=[],
        service_drift=[],
        config_drift=[],
    )
    db_session.add(record)
    await db_session.commit()

    yield node, baseline, record

    await db_session.delete(record)
    await db_session.delete(baseline)
    await db_session.delete(node)
    await db_session.commit()


async def test_list_drift_returns_nodes(admin_client: AsyncClient, node_with_drift):
    response = await admin_client.get("/api/v1/drift")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    hostnames = [n["hostname"] for n in data["items"]]
    assert "drift-test-01" in hostnames


async def test_list_drift_filter_by_severity(admin_client: AsyncClient, node_with_drift):
    response = await admin_client.get("/api/v1/drift?severity=medium")
    assert response.status_code == 200
    items = response.json()["items"]
    # drift_score=45 → medium
    assert any(n["hostname"] == "drift-test-01" for n in items)


async def test_get_node_drift_latest(admin_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    response = await admin_client.get(f"/api/v1/drift/{node.id}/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["drift_score"] == 45
    assert len(data["missing_packages"]) == 1


async def test_get_node_drift_history(admin_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    response = await admin_client.get(f"/api/v1/drift/{node.id}/history")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


async def test_trigger_drift_compute_queues_task(admin_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    with patch("fleet_platform.api.routes.drift.compute_drift") as mock_task:
        response = await admin_client.post(f"/api/v1/drift/{node.id}/compute")
    assert response.status_code == 202
    mock_task.delay.assert_called_once_with(str(node.id))


async def test_drift_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/drift")
    assert response.status_code == 401


async def test_trigger_compute_requires_operator(viewer_client: AsyncClient, node_with_drift):
    node, _, _ = node_with_drift
    response = await viewer_client.post(f"/api/v1/drift/{node.id}/compute")
    assert response.status_code == 403
```

- [ ] **Step 2: Run — expect 404/401**

```bash
source .venv/bin/activate && pytest tests/integration/test_drift_api.py -v
```

- [ ] **Step 3: Create fleet_platform/api/routes/drift.py**

```python
# fleet_platform/api/routes/drift.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.node import Node
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.drift import (
    DriftRecordResponse,
    DriftSummaryResponse,
    drift_severity,
)
from fleet_platform.workers.drift_tasks import compute_drift

router = APIRouter(prefix="/api/v1/drift")

_SEVERITY_RANGES = {
    "clean":    (0, 5),
    "low":      (6, 20),
    "medium":   (21, 50),
    "high":     (51, 80),
    "critical": (81, 100),
}


@router.get("", response_model=PaginatedResponse[DriftSummaryResponse])
async def list_drift(
    severity: str | None = None,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List all nodes ordered by drift_score descending with their latest drift metadata."""
    query = select(Node)

    if severity:
        if severity not in _SEVERITY_RANGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"severity must be one of {list(_SEVERITY_RANGES)}",
            )
        lo, hi = _SEVERITY_RANGES[severity]
        query = query.where(Node.drift_score >= lo, Node.drift_score <= hi)

    query = query.order_by(Node.drift_score.desc())

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    nodes = result.scalars().all()

    # Get latest DriftRecord computed_at + baseline_name for each node
    items = []
    for node in nodes:
        dr_result = await db.execute(
            select(DriftRecord, DesiredStateBaseline)
            .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
            .where(DriftRecord.node_id == node.id)
            .order_by(DriftRecord.computed_at.desc())
            .limit(1)
        )
        row = dr_result.first()
        computed_at = row[0].computed_at if row else None
        baseline_name = row[1].name if row and row[1] else None

        items.append(DriftSummaryResponse(
            node_id=node.id,
            hostname=node.hostname,
            drift_score=node.drift_score,
            severity=drift_severity(node.drift_score),
            computed_at=computed_at,
            baseline_name=baseline_name,
        ))

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{node_id}/latest", response_model=DriftRecordResponse)
async def get_node_drift_latest(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return the most recent drift record for a node with full diff detail."""
    result = await db.execute(
        select(DriftRecord, DesiredStateBaseline)
        .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
        .where(DriftRecord.node_id == node_id)
        .order_by(DriftRecord.computed_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No drift records found for this node")

    dr, baseline = row
    return DriftRecordResponse(
        node_id=dr.node_id,
        baseline_id=dr.baseline_id,
        baseline_name=baseline.name if baseline else None,
        computed_at=dr.computed_at,
        drift_score=dr.drift_score,
        severity=drift_severity(dr.drift_score),
        missing_packages=dr.missing_packages,
        extra_packages=dr.extra_packages,
        version_mismatches=dr.version_mismatches,
        service_drift=dr.service_drift,
        config_drift=dr.config_drift,
    )


@router.get("/{node_id}/history", response_model=PaginatedResponse[DriftSummaryResponse])
async def get_node_drift_history(
    node_id: uuid.UUID,
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return paginated drift score history for a node (newest first)."""
    total = (await db.execute(
        select(func.count()).where(DriftRecord.node_id == node_id)
    )).scalar_one()

    result = await db.execute(
        select(DriftRecord)
        .where(DriftRecord.node_id == node_id)
        .order_by(DriftRecord.computed_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    records = result.scalars().all()

    items = [
        DriftSummaryResponse(
            node_id=r.node_id,
            hostname=None,  # not needed for history timeline
            drift_score=r.drift_score,
            severity=drift_severity(r.drift_score),
            computed_at=r.computed_at,
            baseline_name=None,
        )
        for r in records
    ]

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("/{node_id}/compute", status_code=202)
async def trigger_drift_compute(
    node_id: uuid.UUID,
    _: dict = Depends(require_role("operator", "admin")),
):
    """Enqueue a drift recomputation for a node."""
    compute_drift.delay(str(node_id))
    return {"status": "queued", "node_id": str(node_id)}
```

- [ ] **Step 4: Register drift router in fleet_platform/api/main.py**

Change import to:
```python
from fleet_platform.api.routes import (
    health, auth, nodes, ingest, fleet, groups, search, baselines, drift
)
```

Add after `app.include_router(baselines.router, ...)`:
```python
app.include_router(drift.router, tags=["drift"])
```

- [ ] **Step 5: Run — expect 7 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_drift_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/drift.py fleet_platform/api/main.py \
        tests/integration/test_drift_api.py
git commit -m "feat: drift API — fleet list, per-node latest+history, trigger compute"
```

---

## Task 7: Execution history API

**Files:**
- Create: `fleet_platform/api/routes/executions.py`
- Create: `tests/integration/test_executions_api.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_executions_api.py
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node
import secrets


@pytest.fixture
async def job_with_result(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="exec-node-01.local", hostname="exec-node-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC), status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    job = ExecutionJob(
        salt_jid="20260513100000123456",
        type="highstate",
        target_type="node",
        target_id=node.id,
        triggered_by="salt",
        status="complete",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    result = ExecutionResult(
        job_id=job.id,
        node_id=node.id,
        status="success",
        exit_code=0,
        changes={"pkg": "installed"},
        completed_at=datetime.now(UTC),
    )
    db_session.add(result)
    await db_session.commit()

    yield job, result, node

    await db_session.delete(result)
    await db_session.delete(job)
    await db_session.delete(node)
    await db_session.commit()


async def test_list_executions(admin_client: AsyncClient, job_with_result):
    response = await admin_client.get("/api/v1/executions")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


async def test_list_executions_filter_by_status(admin_client: AsyncClient, job_with_result):
    response = await admin_client.get("/api/v1/executions?status=complete")
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(j["status"] == "complete" for j in items)


async def test_get_execution_job(admin_client: AsyncClient, job_with_result):
    job, _, _ = job_with_result
    response = await admin_client.get(f"/api/v1/executions/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["salt_jid"] == "20260513100000123456"
    assert data["type"] == "highstate"


async def test_get_execution_results(admin_client: AsyncClient, job_with_result):
    job, result, _ = job_with_result
    response = await admin_client.get(f"/api/v1/executions/{job.id}/results")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["status"] == "success"


async def test_get_execution_not_found(admin_client: AsyncClient):
    response = await admin_client.get(f"/api/v1/executions/{uuid.uuid4()}")
    assert response.status_code == 404


```

- [ ] **Step 2: Run — expect 404/401**

```bash
source .venv/bin/activate && pytest tests/integration/test_executions_api.py -v
```

- [ ] **Step 3: Create fleet_platform/api/routes/executions.py**

```python
# fleet_platform/api/routes/executions.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.execution import ExecutionJobResponse, ExecutionResultResponse

router = APIRouter(prefix="/api/v1/executions")


@router.get("", response_model=PaginatedResponse[ExecutionJobResponse])
async def list_executions(
    status: str | None = None,
    node_id: uuid.UUID | None = None,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(ExecutionJob).order_by(ExecutionJob.started_at.desc())

    if status:
        query = query.where(ExecutionJob.status == status)
    if node_id:
        query = query.where(ExecutionJob.target_id == node_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    jobs = result.scalars().all()

    return PaginatedResponse(
        items=[ExecutionJobResponse.model_validate(j) for j in jobs],
        total=total, page=page, per_page=per_page,
    )


@router.get("/{job_id}", response_model=ExecutionJobResponse)
async def get_execution(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(select(ExecutionJob).where(ExecutionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return ExecutionJobResponse.model_validate(job)


@router.get("/{job_id}/results", response_model=PaginatedResponse[ExecutionResultResponse])
async def get_execution_results(
    job_id: uuid.UUID,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(
        select(func.count()).where(ExecutionResult.job_id == job_id)
    )).scalar_one()

    result = await db.execute(
        select(ExecutionResult)
        .where(ExecutionResult.job_id == job_id)
        .order_by(ExecutionResult.completed_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    results = result.scalars().all()

    return PaginatedResponse(
        items=[ExecutionResultResponse.model_validate(r) for r in results],
        total=total, page=page, per_page=per_page,
    )
```

- [ ] **Step 4: Register in fleet_platform/api/main.py**

Add `executions` to the import and register:

```python
from fleet_platform.api.routes import (
    health, auth, nodes, ingest, fleet, groups, search, baselines, drift, executions
)
```

Add after `app.include_router(drift.router, ...)`:
```python
app.include_router(executions.router, tags=["executions"])
```

- [ ] **Step 5: Run — expect 5 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_executions_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/executions.py fleet_platform/api/main.py \
        tests/integration/test_executions_api.py
git commit -m "feat: execution history API — list, detail, per-job results"
```

---

## Task 8: Full test suite run + smoke test

- [ ] **Step 1: Ensure Docker is running**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "postgres|redis"
```

If not: `cd /home/dk/Documents/git/kri/deploy && docker compose up -d && cd ..`

- [ ] **Step 2: Run full suite**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate && pytest --tb=short -q
```

Expected: 98 existing + ~38 new ≈ **136 passed**, 0 failed.

- [ ] **Step 3: Smoke-test new endpoints**

```bash
source .venv/bin/activate
uvicorn fleet_platform.api.main:app --port 8000 &
PID=$!
sleep 3

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create a baseline
curl -s -X POST http://localhost:8000/api/v1/baselines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke-test","state_json":{"packages":{"required":[{"name":"git"}]}},"git_commit_sha":"abc"}' | \
  python3 -m json.tool

# Fleet drift list
curl -s http://localhost:8000/api/v1/drift -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Execution history
curl -s http://localhost:8000/api/v1/executions -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

kill $PID
```

- [ ] **Step 4: Final commit**

```bash
git add -A && git status
git diff --cached --stat
# Only commit if there are actual changes
git commit -m "chore: plan 4 complete — drift engine, baselines, execution history, all tests passing" 2>/dev/null || echo "nothing new to commit"
```

---

## Plan 4 Self-Review

**Spec coverage (RFC §10 Drift Detection):**
- ✅ Drift engine — pure compute_drift() with package/service diff + weighted scoring
- ✅ Drift scoring 0–100 with severity tiers (clean/low/medium/high/critical)
- ✅ Historical drift timeline — DriftRecord TimescaleDB hypertable exposed via /history
- ✅ Drift APIs — fleet list, per-node latest, history, trigger compute
- ✅ Diff visualization data — missing_packages, extra_packages, version_mismatches, service_drift exposed in DriftRecordResponse
- ✅ Desired state model — DesiredStateBaseline with target_type (global/group/node)
- ✅ Actual state collection — from NodeFact.grains (written by grain ingest in Plan 2)
- ✅ Baseline priority — node > group > global in find_baseline_for_node_sync()
- ✅ Incremental drift processing — compute_drift Celery task triggered on grain ingest (Plan 2)

**Spec coverage (RFC §8 Execution History):**
- ✅ GET /api/v1/executions — list with status + node_id filter
- ✅ GET /api/v1/executions/{id} — job detail
- ✅ GET /api/v1/executions/{id}/results — per-node results

**Not in this plan:**
- Config drift (requires config file facts beyond what Salt grains provide) → future
- Automated remediation → future
- SBOM pipeline → Plan 5

**Type consistency:**
- `compute_drift(node_id: str)` in drift_tasks.py matches `compute_drift.delay(str(node_id))` in drift.py ✅
- `find_baseline_for_node_sync(node_uuid, db)` in drift_tasks.py matches function signature in baseline_loader.py ✅
- `DriftResult.drift_score: int` matches `DriftRecord.drift_score: SmallInteger` (both int, score 0–100) ✅
- `drift_severity(score: int) -> str` used in both drift list and drift record response ✅

**Placeholder scan:** No TBDs. All code complete. ✅
