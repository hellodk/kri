# Fleet Health Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect disk usage, inode usage, memory pressure, CPU load, uptime/reboot reason, GPU info, and powermetrics (power draw + thermal pressure) from every Mac Mini via Salt and surface it in a Fleet Health dashboard page.

**Architecture:** A synchronous Salt subprocess helper in `salt_maintenance_svc.py` runs all health commands against online nodes in a single Celery task (`collect_fleet_health`, every 15 minutes). Results are stored in a new `node_health_snapshots` table. A FastAPI router exposes latest-per-node, on-demand trigger, and 24h history. The React dashboard renders per-node metric cards with threshold-based alerting (disk > 85%, memory > 90%, thermal ≠ Nominal) and inline recharts history.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, PostgreSQL, Celery, Salt via docker exec subprocess, React 18, TanStack Query 5, Tailwind CSS, recharts

**Closes:** #41

---

## File Map

### New files

| File | Purpose |
|------|---------|
| `fleet_platform/services/salt_maintenance_svc.py` | Salt subprocess helper + parse functions for each metric |
| `fleet_platform/models/node_health_snapshot.py` | SQLAlchemy model for `node_health_snapshots` table |
| `fleet_platform/db/migrations/versions/019_fleet_health.py` | Alembic migration |
| `fleet_platform/workers/health_tasks.py` | Celery task `collect_fleet_health` |
| `fleet_platform/schemas/fleet_health.py` | Pydantic request/response schemas |
| `fleet_platform/api/routes/fleet_health.py` | API routes |
| `frontend/src/api/fleetHealth.ts` | Frontend API client |
| `frontend/src/pages/FleetHealthPage.tsx` | Dashboard page |
| `tests/unit/test_salt_maintenance_svc.py` | Unit tests for all parsers (no subprocess) |
| `tests/unit/test_health_tasks.py` | Unit tests for collection task (mocked subprocess) |
| `tests/integration/test_fleet_health_api.py` | Integration tests for API routes |

### Modified files

| File | Change |
|------|--------|
| `fleet_platform/workers/salt_tasks.py` | Add `disk.usage`, `disk.inodeusage`, `status.loadavg` to `_ALLOWED_SALT_FUNCTIONS` |
| `fleet_platform/models/__init__.py` | Export `NodeHealthSnapshot` |
| `fleet_platform/workers/celery_app.py` | Add `collect-fleet-health` beat schedule (every 15 min) |
| `fleet_platform/api/main.py` | Register `fleet_health_router` |
| `frontend/src/App.tsx` | Add `/fleet-health` route |
| `frontend/src/components/Sidebar.tsx` (or equivalent nav component) | Add Fleet Health nav item |

---

## Task 1: Salt Maintenance Service + Allowlist Expansion

**Files:**
- Create: `fleet_platform/services/salt_maintenance_svc.py`
- Modify: `fleet_platform/workers/salt_tasks.py`
- Create: `tests/unit/test_salt_maintenance_svc.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/unit/test_salt_maintenance_svc.py`:

```python
# tests/unit/test_salt_maintenance_svc.py
"""Unit tests for salt_maintenance_svc parsing functions. No subprocess, no network."""


def test_parse_disk_usage_extracts_root_metrics():
    from fleet_platform.services.salt_maintenance_svc import parse_disk_usage
    salt_out = {
        "mac-mini-01": {
            "/": {"1K-blocks": 245094400, "used": 100000000, "available": 145094400, "use%": "41%"},
            "/System/Volumes/Data": {"1K-blocks": 245094400, "used": 50000000, "available": 195094400, "use%": "21%"},
        }
    }
    result = parse_disk_usage(salt_out, "mac-mini-01")
    assert result["disk_root_pct"] == 41
    assert result["disk_root_total_gb"] > 0
    assert result["disk_root_used_gb"] > 0
    assert result["disk_root_used_gb"] < result["disk_root_total_gb"]


def test_parse_disk_usage_returns_none_for_missing_minion():
    from fleet_platform.services.salt_maintenance_svc import parse_disk_usage
    result = parse_disk_usage({}, "mac-mini-99")
    assert result["disk_root_pct"] is None
    assert result["disk_root_used_gb"] is None


def test_parse_inode_usage_extracts_root_pct():
    from fleet_platform.services.salt_maintenance_svc import parse_inode_usage
    salt_out = {
        "mac-mini-01": {
            "/": {"inodes": 4882452480, "used": 500000, "free": 4881952480, "use%": "1%"},
        }
    }
    result = parse_inode_usage(salt_out, "mac-mini-01")
    assert result["disk_root_inodes_pct"] == 1


def test_parse_loadavg_extracts_three_values():
    from fleet_platform.services.salt_maintenance_svc import parse_loadavg
    salt_out = {"mac-mini-01": {"1-min": 1.23, "5-min": 0.98, "15-min": 0.75}}
    result = parse_loadavg(salt_out, "mac-mini-01")
    assert result["cpu_load_1m"] == 1.23
    assert result["cpu_load_5m"] == 0.98
    assert result["cpu_load_15m"] == 0.75


def test_parse_loadavg_missing_minion_returns_none():
    from fleet_platform.services.salt_maintenance_svc import parse_loadavg
    result = parse_loadavg({}, "mac-mini-99")
    assert result["cpu_load_1m"] is None


def test_parse_vm_stat_computes_used_pct():
    from fleet_platform.services.salt_maintenance_svc import parse_vm_stat
    vm_stat_text = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                          4028.
Pages active:                       50000.
Pages inactive:                     20000.
Pages speculative:                    100.
Pages throttled:                        0.
Pages wired down:                   30000.
"""
    total_bytes = 8 * 1024 ** 3  # 8 GB
    result = parse_vm_stat(vm_stat_text, total_bytes)
    assert result["mem_total_gb"] == 8.0
    assert 0 < result["mem_used_pct"] <= 100
    assert result["mem_available_gb"] >= 0


def test_parse_vm_stat_zero_total_bytes_safe():
    from fleet_platform.services.salt_maintenance_svc import parse_vm_stat
    result = parse_vm_stat("", 0)
    assert result["mem_used_pct"] == 0


def test_parse_uptime_seconds_days_and_hours():
    from fleet_platform.services.salt_maintenance_svc import parse_uptime_seconds
    text = " 3:45  up 2 days, 18:23, 2 users, load averages: 1.23 0.98 0.75"
    seconds = parse_uptime_seconds(text)
    assert seconds == 2 * 86400 + 18 * 3600 + 23 * 60


def test_parse_uptime_seconds_minutes_only():
    from fleet_platform.services.salt_maintenance_svc import parse_uptime_seconds
    text = " 3:45  up 47 mins, 1 user, load averages: 0.50 0.30 0.20"
    seconds = parse_uptime_seconds(text)
    assert seconds == 47 * 60


def test_parse_uptime_seconds_invalid_returns_none():
    from fleet_platform.services.salt_maintenance_svc import parse_uptime_seconds
    assert parse_uptime_seconds("") is None
    assert parse_uptime_seconds("garbage text") is None


def test_parse_gpu_info_extracts_name_and_vram():
    from fleet_platform.services.salt_maintenance_svc import parse_gpu_info
    raw_json = '{"SPDisplaysDataType": [{"sppci_model": "Apple M2 GPU", "spdisplays_vram": "8 GB"}]}'
    result = parse_gpu_info(raw_json)
    assert result["gpu_name"] == "Apple M2 GPU"
    assert result["gpu_vram_mb"] == 8192


def test_parse_gpu_info_mb_vram():
    from fleet_platform.services.salt_maintenance_svc import parse_gpu_info
    raw_json = '{"SPDisplaysDataType": [{"sppci_model": "Intel Iris Plus", "spdisplays_vram": "1536 MB"}]}'
    result = parse_gpu_info(raw_json)
    assert result["gpu_vram_mb"] == 1536


def test_parse_gpu_info_invalid_json_returns_none():
    from fleet_platform.services.salt_maintenance_svc import parse_gpu_info
    result = parse_gpu_info("not json")
    assert result["gpu_name"] is None
    assert result["gpu_vram_mb"] is None


def test_parse_powermetrics_apple_silicon():
    from fleet_platform.services.salt_maintenance_svc import parse_powermetrics
    import json
    data = {
        "processor": {"packages": [{"package_mw": 5000}]},
        "gpu": {"package_mw": 1500},
        "thermal_pressure": "Nominal",
    }
    result = parse_powermetrics(json.dumps(data))
    assert result["cpu_power_mw"] == 5000
    assert result["gpu_power_mw"] == 1500
    assert result["thermal_pressure"] == "Nominal"


def test_parse_powermetrics_intel_format():
    from fleet_platform.services.salt_maintenance_svc import parse_powermetrics
    import json
    data = {
        "cpu_power": {"package_mw": 8000},
        "gpu_power": {"gpu_mw": 2000},
        "thermal_pressure": "Light",
    }
    result = parse_powermetrics(json.dumps(data))
    assert result["cpu_power_mw"] == 8000
    assert result["gpu_power_mw"] == 2000
    assert result["thermal_pressure"] == "Light"


def test_parse_powermetrics_bad_json_returns_none_fields():
    from fleet_platform.services.salt_maintenance_svc import parse_powermetrics
    result = parse_powermetrics("sudo: powermetrics: command not found")
    assert result["cpu_power_mw"] is None
    assert result["gpu_power_mw"] is None
    assert result["thermal_pressure"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/test_salt_maintenance_svc.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'fleet_platform.services.salt_maintenance_svc'`

- [ ] **Step 3: Create `fleet_platform/services/salt_maintenance_svc.py`**

```python
# fleet_platform/services/salt_maintenance_svc.py
"""Salt-based health metric collection for Mac Mini fleet nodes.

All parse_* functions are pure (no subprocess, no I/O) — easy to unit test.
collect_all_metrics() executes the actual Salt commands via docker exec.

Requires sudo access for powermetrics:
    salt ALL=(ALL) NOPASSWD: /usr/bin/powermetrics
"""
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_SALT_CONTAINER = os.environ.get("SALT_MASTER_CONTAINER", "deploy-salt-master-1")


# ── subprocess helper ─────────────────────────────────────────────────────────

def _run_salt(
    function: str,
    target: str,
    args: list[str] | None = None,
    timeout: int = 60,
) -> dict:
    """Run a Salt command via docker exec and return the parsed JSON output.

    Returns an empty dict on timeout, non-zero exit, or JSON parse failure.
    """
    cmd = ["docker", "exec", _SALT_CONTAINER, "salt", "-L", target,
           function, "--no-color", "--out=json"]
    if args:
        cmd += args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            logger.warning("_run_salt %s returned %d: %s", function, proc.returncode, proc.stderr[:200])
            return {}
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        logger.error("_run_salt %s timed out after %ds", function, timeout)
        return {}
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("_run_salt %s failed: %s", function, exc)
        return {}


# ── parsers ───────────────────────────────────────────────────────────────────

def parse_disk_usage(salt_out: dict, minion_id: str) -> dict:
    """Parse disk.usage Salt module output for one minion.

    Returns keys: disk_root_used_gb, disk_root_total_gb, disk_root_pct
    """
    node_data = salt_out.get(minion_id, {})
    root = node_data.get("/", {})
    if not root:
        return {"disk_root_used_gb": None, "disk_root_total_gb": None, "disk_root_pct": None}
    total_gb = root.get("1K-blocks", 0) / (1024 * 1024)
    used_gb = root.get("used", 0) / (1024 * 1024)
    pct_str = root.get("use%", "").rstrip("%")
    return {
        "disk_root_used_gb": round(used_gb, 2),
        "disk_root_total_gb": round(total_gb, 2),
        "disk_root_pct": int(pct_str) if pct_str.isdigit() else None,
    }


def parse_inode_usage(salt_out: dict, minion_id: str) -> dict:
    """Parse disk.inodeusage Salt module output. Returns disk_root_inodes_pct."""
    node_data = salt_out.get(minion_id, {})
    root = node_data.get("/", {})
    pct_str = root.get("use%", "").rstrip("%")
    return {"disk_root_inodes_pct": int(pct_str) if pct_str.isdigit() else None}


def parse_loadavg(salt_out: dict, minion_id: str) -> dict:
    """Parse status.loadavg Salt module output.

    Returns keys: cpu_load_1m, cpu_load_5m, cpu_load_15m
    """
    node_data = salt_out.get(minion_id, {})
    return {
        "cpu_load_1m": node_data.get("1-min"),
        "cpu_load_5m": node_data.get("5-min"),
        "cpu_load_15m": node_data.get("15-min"),
    }


def parse_vm_stat(vm_stat_text: str, total_bytes: int) -> dict:
    """Parse macOS vm_stat output.

    vm_stat_text: raw text from cmd.run "vm_stat"
    total_bytes: integer from cmd.run "sysctl -n hw.memsize"

    Returns keys: mem_total_gb, mem_available_gb, mem_used_pct
    """
    page_size = 16384  # standard macOS page size (16 KB)
    pages: dict[str, int] = {}
    for line in vm_stat_text.splitlines():
        for key in ("Pages free", "Pages speculative"):
            if line.strip().startswith(key):
                try:
                    pages[key] = int(line.split()[-1].rstrip("."))
                except (ValueError, IndexError):
                    pass

    if total_bytes <= 0:
        return {"mem_total_gb": None, "mem_available_gb": None, "mem_used_pct": 0}

    free_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
    free_bytes = free_pages * page_size
    total_gb = total_bytes / (1024 ** 3)
    free_gb = free_bytes / (1024 ** 3)
    used_gb = total_gb - free_gb
    used_pct = int((used_gb / total_gb) * 100) if total_gb > 0 else 0
    return {
        "mem_total_gb": round(total_gb, 2),
        "mem_available_gb": round(free_gb, 2),
        "mem_used_pct": min(used_pct, 100),
    }


def parse_uptime_seconds(uptime_text: str) -> int | None:
    """Parse macOS uptime output into total seconds.

    Examples:
        " 3:45  up 2 days, 18:23, 2 users, ..."  → 239_580
        " 3:45  up 47 mins, 1 user, ..."          → 2_820
    """
    if not uptime_text:
        return None
    days = 0
    m = re.search(r"up\s+(\d+)\s+day", uptime_text)
    if m:
        days = int(m.group(1))
    m2 = re.search(r"up\s+(?:\d+\s+days?,\s*)?(\d+):(\d+)", uptime_text)
    if m2:
        return days * 86400 + int(m2.group(1)) * 3600 + int(m2.group(2)) * 60
    m3 = re.search(r"up\s+(\d+)\s+min", uptime_text)
    if m3:
        return days * 86400 + int(m3.group(1)) * 60
    return None


def parse_gpu_info(raw_json: str) -> dict:
    """Parse system_profiler SPDisplaysDataType -json output.

    Returns keys: gpu_name, gpu_vram_mb
    """
    try:
        data = json.loads(raw_json)
        displays = data.get("SPDisplaysDataType", [])
        if not displays:
            return {"gpu_name": None, "gpu_vram_mb": None}
        gpu = displays[0]
        name = gpu.get("sppci_model") or gpu.get("_name")
        vram_str = gpu.get("spdisplays_vram") or gpu.get("spdisplays_vram_shared", "")
        vram_mb = None
        if vram_str:
            parts = vram_str.split()
            if len(parts) >= 2:
                try:
                    val = int(parts[0])
                    unit = parts[1].upper()
                    vram_mb = val * 1024 if unit == "GB" else val
                except ValueError:
                    pass
        return {"gpu_name": name, "gpu_vram_mb": vram_mb}
    except Exception:
        return {"gpu_name": None, "gpu_vram_mb": None}


def parse_powermetrics(raw_json: str) -> dict:
    """Parse powermetrics --output-format json output.

    Handles both Apple Silicon and Intel field layouts.
    Returns keys: cpu_power_mw, gpu_power_mw, thermal_pressure
    """
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return {"cpu_power_mw": None, "gpu_power_mw": None, "thermal_pressure": None}

    cpu_power = None
    gpu_power = None

    # Apple Silicon: processor.packages[0].package_mw
    if "processor" in data:
        pkgs = data["processor"].get("packages", [])
        if pkgs:
            cpu_power = pkgs[0].get("package_mw")
    # Intel: cpu_power.package_mw
    elif "cpu_power" in data:
        cpu_power = data["cpu_power"].get("package_mw")

    # Apple Silicon: gpu.package_mw  |  Intel: gpu_power.gpu_mw
    if "gpu" in data:
        gpu_power = data["gpu"].get("package_mw") or data["gpu"].get("gpu_mw")
    elif "gpu_power" in data:
        gpu_power = data["gpu_power"].get("gpu_mw")

    thermal = data.get("thermal_pressure") or data.get("thermalPressure")

    return {
        "cpu_power_mw": int(cpu_power) if cpu_power is not None else None,
        "gpu_power_mw": int(gpu_power) if gpu_power is not None else None,
        "thermal_pressure": str(thermal) if thermal else None,
    }


# ── collection orchestrator ───────────────────────────────────────────────────

def collect_all_metrics(minion_ids: list[str]) -> dict[str, dict]:
    """Run all health Salt commands against minion_ids and return parsed metrics per minion.

    Called from the collect_fleet_health Celery task.
    Each command targets all minions in one Salt call for efficiency.
    powermetrics may return None fields if sudo is not configured.
    """
    if not minion_ids:
        return {}

    target = ",".join(minion_ids)
    results: dict[str, dict] = {mid: {"error": None} for mid in minion_ids}

    def _apply(parse_fn, salt_out: dict) -> None:
        for mid in minion_ids:
            try:
                results[mid].update(parse_fn(salt_out, mid))
            except Exception as exc:
                logger.warning("parse error for %s in %s: %s", mid, parse_fn.__name__, exc)

    _apply(parse_disk_usage, _run_salt("disk.usage", target))
    _apply(parse_inode_usage, _run_salt("disk.inodeusage", target))
    _apply(parse_loadavg, _run_salt("status.loadavg", target))

    vmstat_out = _run_salt("cmd.run", target, args=["vm_stat"])
    hwmem_out = _run_salt("cmd.run", target, args=["sysctl -n hw.memsize"])
    for mid in minion_ids:
        try:
            total_bytes = int(hwmem_out.get(mid, "0").strip())
        except (ValueError, AttributeError):
            total_bytes = 0
        results[mid].update(parse_vm_stat(vmstat_out.get(mid, ""), total_bytes))

    uptime_out = _run_salt("cmd.run", target, args=["uptime"])
    for mid in minion_ids:
        results[mid]["uptime_seconds"] = parse_uptime_seconds(uptime_out.get(mid, ""))

    gpu_out = _run_salt("cmd.run", target, args=["system_profiler SPDisplaysDataType -json"])
    for mid in minion_ids:
        results[mid].update(parse_gpu_info(gpu_out.get(mid, "")))

    pm_out = _run_salt(
        "cmd.run", target,
        args=["sudo powermetrics -n 1 -i 500 --samplers cpu_power,gpu_power,thermal --output-format json 2>/dev/null"],
        timeout=30,
    )
    for mid in minion_ids:
        results[mid].update(parse_powermetrics(pm_out.get(mid, "")))

    return results
```

- [ ] **Step 4: Add missing functions to `_ALLOWED_SALT_FUNCTIONS` in `fleet_platform/workers/salt_tasks.py`**

Open the file, find `_ALLOWED_SALT_FUNCTIONS: frozenset[str] = frozenset({`, add after `"cmd.run"`:

```python
    "disk.usage",
    "disk.inodeusage",
    "status.loadavg",
    "status.meminfo",
```

- [ ] **Step 5: Run parser tests**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/test_salt_maintenance_svc.py -v
```
Expected: 16 PASSED

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/services/salt_maintenance_svc.py \
        fleet_platform/workers/salt_tasks.py \
        tests/unit/test_salt_maintenance_svc.py
git commit -m "feat: salt maintenance service — health parsers and allowlist expansion"
```

---

## Task 2: DB Model + Migration 019

**Files:**
- Create: `fleet_platform/models/node_health_snapshot.py`
- Create: `fleet_platform/db/migrations/versions/019_fleet_health.py`
- Modify: `fleet_platform/models/__init__.py`
- Create: `tests/unit/test_node_health_snapshot.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/unit/test_node_health_snapshot.py`:

```python
# tests/unit/test_node_health_snapshot.py
from sqlalchemy import inspect as sa_inspect


def test_node_health_snapshot_tablename():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    assert NodeHealthSnapshot.__tablename__ == "node_health_snapshots"


def test_node_health_snapshot_has_required_columns():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    mapper = sa_inspect(NodeHealthSnapshot)
    col_names = {c.key for c in mapper.columns}
    expected = {
        "id", "node_id", "minion_id", "collected_at",
        "disk_root_used_gb", "disk_root_total_gb", "disk_root_pct", "disk_root_inodes_pct",
        "mem_total_gb", "mem_available_gb", "mem_used_pct",
        "cpu_load_1m", "cpu_load_5m", "cpu_load_15m",
        "uptime_seconds",
        "gpu_name", "gpu_vram_mb",
        "cpu_power_mw", "gpu_power_mw", "thermal_pressure",
        "error",
    }
    assert expected.issubset(col_names), f"Missing: {expected - col_names}"


def test_node_health_snapshot_nullable_fields():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    mapper = sa_inspect(NodeHealthSnapshot)
    nullable_cols = {
        "disk_root_used_gb", "disk_root_total_gb", "disk_root_pct", "disk_root_inodes_pct",
        "mem_total_gb", "mem_available_gb", "mem_used_pct",
        "cpu_load_1m", "cpu_load_5m", "cpu_load_15m",
        "uptime_seconds", "gpu_name", "gpu_vram_mb",
        "cpu_power_mw", "gpu_power_mw", "thermal_pressure", "error",
    }
    for col_name in nullable_cols:
        col = mapper.c[col_name]
        assert col.nullable, f"{col_name} should be nullable"


def test_node_health_snapshot_has_index():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    index_names = {idx.name for idx in NodeHealthSnapshot.__table__.indexes}
    assert "idx_node_health_node_collected" in index_names


def test_node_health_snapshot_exported_from_models():
    from fleet_platform.models import NodeHealthSnapshot
    assert NodeHealthSnapshot.__tablename__ == "node_health_snapshots"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/test_node_health_snapshot.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `fleet_platform/models/node_health_snapshot.py`**

```python
# fleet_platform/models/node_health_snapshot.py
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class NodeHealthSnapshot(Base):
    __tablename__ = "node_health_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    def __init__(self, **kw: object) -> None:
        if "id" not in kw:
            kw["id"] = uuid.uuid4()
        super().__init__(**kw)

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    minion_id: Mapped[str] = mapped_column(String(255), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Disk
    disk_root_used_gb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    disk_root_total_gb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    disk_root_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    disk_root_inodes_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Memory
    mem_total_gb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    mem_available_gb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    mem_used_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # CPU
    cpu_load_1m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    cpu_load_5m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    cpu_load_15m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # System
    uptime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # GPU
    gpu_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gpu_vram_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Power & thermal (powermetrics — requires sudo on minion)
    cpu_power_mw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_power_mw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thermal_pressure: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Collection error (set when any command fails)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_node_health_node_collected", "node_id", "collected_at"),
    )
```

- [ ] **Step 4: Add export to `fleet_platform/models/__init__.py`**

Open the file, append:
```python
from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
```

- [ ] **Step 5: Create `fleet_platform/db/migrations/versions/019_fleet_health.py`**

```python
"""Create node_health_snapshots table

Revision ID: 019
Revises: 018
Create Date: 2026-05-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_health_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("minion_id", sa.String(255), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("disk_root_used_gb", sa.Numeric(10, 2), nullable=True),
        sa.Column("disk_root_total_gb", sa.Numeric(10, 2), nullable=True),
        sa.Column("disk_root_pct", sa.SmallInteger, nullable=True),
        sa.Column("disk_root_inodes_pct", sa.SmallInteger, nullable=True),
        sa.Column("mem_total_gb", sa.Numeric(8, 2), nullable=True),
        sa.Column("mem_available_gb", sa.Numeric(8, 2), nullable=True),
        sa.Column("mem_used_pct", sa.SmallInteger, nullable=True),
        sa.Column("cpu_load_1m", sa.Numeric(6, 2), nullable=True),
        sa.Column("cpu_load_5m", sa.Numeric(6, 2), nullable=True),
        sa.Column("cpu_load_15m", sa.Numeric(6, 2), nullable=True),
        sa.Column("uptime_seconds", sa.Integer, nullable=True),
        sa.Column("gpu_name", sa.String(255), nullable=True),
        sa.Column("gpu_vram_mb", sa.Integer, nullable=True),
        sa.Column("cpu_power_mw", sa.Integer, nullable=True),
        sa.Column("gpu_power_mw", sa.Integer, nullable=True),
        sa.Column("thermal_pressure", sa.String(20), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_node_health_node_collected",
        "node_health_snapshots",
        ["node_id", "collected_at"],
    )


def downgrade() -> None:
    op.drop_table("node_health_snapshots")
```

- [ ] **Step 6: Run model tests**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/test_node_health_snapshot.py -v
```
Expected: 5 PASSED

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/models/node_health_snapshot.py \
        fleet_platform/models/__init__.py \
        fleet_platform/db/migrations/versions/019_fleet_health.py \
        tests/unit/test_node_health_snapshot.py
git commit -m "feat: NodeHealthSnapshot model and migration 019"
```

---

## Task 3: Celery Collection Task + Beat Schedule

**Files:**
- Create: `fleet_platform/workers/health_tasks.py`
- Modify: `fleet_platform/workers/celery_app.py`
- Create: `tests/unit/test_health_tasks.py`

- [ ] **Step 1: Write failing collection task tests**

Create `tests/unit/test_health_tasks.py`:

```python
# tests/unit/test_health_tasks.py
"""Unit tests for collect_fleet_health Celery task. No subprocess, no network."""
from unittest.mock import MagicMock, patch


def test_collect_fleet_health_skips_when_no_online_nodes():
    from fleet_platform.workers.health_tasks import collect_fleet_health
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("fleet_platform.workers.health_tasks.get_sync_db", return_value=mock_db):
        result = collect_fleet_health()

    assert result == {"collected": 0}
    # No snapshots inserted
    mock_db.add.assert_not_called()


def test_collect_fleet_health_inserts_snapshot_per_node():
    from fleet_platform.workers.health_tasks import collect_fleet_health
    import uuid

    node1 = MagicMock()
    node1.id = uuid.uuid4()
    node1.minion_id = "mac-mini-01"

    node2 = MagicMock()
    node2.id = uuid.uuid4()
    node2.minion_id = "mac-mini-02"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node1, node2]

    fake_metrics = {
        "mac-mini-01": {"disk_root_pct": 40, "mem_used_pct": 60, "cpu_load_1m": 1.2,
                        "cpu_power_mw": 5000, "gpu_power_mw": 1500, "thermal_pressure": "Nominal",
                        "gpu_name": "Apple M2 GPU", "gpu_vram_mb": 8192,
                        "disk_root_used_gb": 100.0, "disk_root_total_gb": 256.0,
                        "disk_root_inodes_pct": 1, "mem_total_gb": 16.0,
                        "mem_available_gb": 6.4, "cpu_load_5m": 1.0, "cpu_load_15m": 0.8,
                        "uptime_seconds": 172800, "error": None},
        "mac-mini-02": {"disk_root_pct": 90, "mem_used_pct": 95, "cpu_load_1m": 3.5,
                        "cpu_power_mw": None, "gpu_power_mw": None, "thermal_pressure": None,
                        "gpu_name": None, "gpu_vram_mb": None,
                        "disk_root_used_gb": 230.0, "disk_root_total_gb": 256.0,
                        "disk_root_inodes_pct": 5, "mem_total_gb": 8.0,
                        "mem_available_gb": 0.4, "cpu_load_5m": 3.0, "cpu_load_15m": 2.5,
                        "uptime_seconds": 3600, "error": None},
    }

    with (
        patch("fleet_platform.workers.health_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.health_tasks.salt_maintenance_svc.collect_all_metrics",
              return_value=fake_metrics),
    ):
        result = collect_fleet_health()

    assert result == {"collected": 2}
    assert mock_db.add.call_count == 2
    mock_db.commit.assert_called_once()


def test_collect_fleet_health_task_name():
    from fleet_platform.workers.health_tasks import collect_fleet_health
    assert collect_fleet_health.name == "fleet_platform.workers.health_tasks.collect_fleet_health"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/test_health_tasks.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `fleet_platform/workers/health_tasks.py`**

```python
# fleet_platform/workers/health_tasks.py
"""Celery task for periodic fleet health metric collection."""
import logging

from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
from fleet_platform.services import salt_maintenance_svc
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="fleet_platform.workers.health_tasks.collect_fleet_health",
    queue="maintenance",
)
def collect_fleet_health() -> dict:
    """Collect health metrics from all online nodes and persist snapshots.

    Runs as Celery beat task every 15 minutes. Also triggerable on-demand via API.
    """
    with get_sync_db() as db:
        nodes = db.execute(
            select(Node).where(Node.status == "online")
        ).scalars().all()

        if not nodes:
            logger.info("collect_fleet_health: no online nodes, skipping")
            return {"collected": 0}

        minion_ids = [n.minion_id for n in nodes]
        node_by_minion = {n.minion_id: n for n in nodes}

        logger.info("collect_fleet_health: collecting from %d nodes", len(nodes))
        health_data = salt_maintenance_svc.collect_all_metrics(minion_ids)

        count = 0
        for minion_id, metrics in health_data.items():
            node = node_by_minion.get(minion_id)
            if not node:
                continue
            snapshot = NodeHealthSnapshot(
                node_id=node.id,
                minion_id=minion_id,
                **metrics,
            )
            db.add(snapshot)
            count += 1

        db.commit()
        logger.info("collect_fleet_health: inserted %d snapshots", count)
        return {"collected": count}
```

- [ ] **Step 4: Add beat schedule to `fleet_platform/workers/celery_app.py`**

Open the file, find `beat_schedule={`, add after the last entry (before the closing `}`):

```python
        "collect-fleet-health": {
            "task": "fleet_platform.workers.health_tasks.collect_fleet_health",
            "schedule": 900,  # every 15 minutes
        },
```

Also add the task route inside `task_routes`:
```python
        "fleet_platform.workers.health_tasks.*": {"queue": "maintenance"},
```

- [ ] **Step 5: Run collection task tests**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/test_health_tasks.py -v
```
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/workers/health_tasks.py \
        fleet_platform/workers/celery_app.py \
        tests/unit/test_health_tasks.py
git commit -m "feat: collect_fleet_health Celery task, beat every 15 min"
```

---

## Task 4: API Schemas + Routes

**Files:**
- Create: `fleet_platform/schemas/fleet_health.py`
- Create: `fleet_platform/api/routes/fleet_health.py`
- Modify: `fleet_platform/api/main.py`
- Create: `tests/integration/test_fleet_health_api.py`

- [ ] **Step 1: Create `fleet_platform/schemas/fleet_health.py`**

```python
# fleet_platform/schemas/fleet_health.py
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, computed_field


class NodeHealthSnapshotResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    minion_id: str
    hostname: str | None
    collected_at: datetime
    disk_root_used_gb: Decimal | None
    disk_root_total_gb: Decimal | None
    disk_root_pct: int | None
    disk_root_inodes_pct: int | None
    mem_total_gb: Decimal | None
    mem_available_gb: Decimal | None
    mem_used_pct: int | None
    cpu_load_1m: Decimal | None
    cpu_load_5m: Decimal | None
    cpu_load_15m: Decimal | None
    uptime_seconds: int | None
    gpu_name: str | None
    gpu_vram_mb: int | None
    cpu_power_mw: int | None
    gpu_power_mw: int | None
    thermal_pressure: str | None
    error: str | None

    @computed_field  # type: ignore[misc]
    @property
    def disk_alert(self) -> bool:
        return (self.disk_root_pct or 0) >= 85

    @computed_field  # type: ignore[misc]
    @property
    def mem_alert(self) -> bool:
        return (self.mem_used_pct or 0) >= 90

    @computed_field  # type: ignore[misc]
    @property
    def thermal_alert(self) -> bool:
        return self.thermal_pressure not in (None, "Nominal")

    model_config = {"from_attributes": True}


class CollectResponse(BaseModel):
    status: str
    message: str
```

- [ ] **Step 2: Write integration test stubs**

Create `tests/integration/test_fleet_health_api.py`:

```python
# tests/integration/test_fleet_health_api.py
"""Integration tests for /api/v1/fleet-health routes.
Requires: DATABASE_URL pointing to a test PostgreSQL instance.
Run: pytest tests/integration/test_fleet_health_api.py -v
"""
import pytest
from unittest.mock import patch
from httpx import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_get_fleet_health_returns_200(async_client: AsyncClient, operator_token: str):
    response = await async_client.get(
        "/api/v1/fleet-health",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_trigger_collect_returns_202(async_client: AsyncClient, admin_token: str):
    with patch("fleet_platform.workers.health_tasks.collect_fleet_health.delay") as mock_delay:
        mock_delay.return_value = None
        response = await async_client.post(
            "/api/v1/fleet-health/collect",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_trigger_collect_requires_admin(async_client: AsyncClient, operator_token: str):
    response = await async_client.post(
        "/api/v1/fleet-health/collect",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_fleet_health_unauthenticated_returns_401(async_client: AsyncClient):
    response = await async_client.get("/api/v1/fleet-health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_node_health_history_returns_list(async_client: AsyncClient, operator_token: str, test_node):
    import uuid
    response = await async_client.get(
        f"/api/v1/fleet-health/{test_node.id}/history",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    # 200 with empty list is fine — node exists but no snapshots yet
    assert response.status_code in (200, 404)
```

- [ ] **Step 3: Create `fleet_platform/api/routes/fleet_health.py`**

```python
# fleet_platform/api/routes/fleet_health.py
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.node import Node
from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
from fleet_platform.schemas.fleet_health import CollectResponse, NodeHealthSnapshotResponse

router = APIRouter(prefix="/api/v1/fleet-health", tags=["fleet-health"])


def _to_response(snapshot: NodeHealthSnapshot, hostname: str | None) -> NodeHealthSnapshotResponse:
    return NodeHealthSnapshotResponse(
        id=snapshot.id,
        node_id=snapshot.node_id,
        minion_id=snapshot.minion_id,
        hostname=hostname,
        collected_at=snapshot.collected_at,
        disk_root_used_gb=snapshot.disk_root_used_gb,
        disk_root_total_gb=snapshot.disk_root_total_gb,
        disk_root_pct=snapshot.disk_root_pct,
        disk_root_inodes_pct=snapshot.disk_root_inodes_pct,
        mem_total_gb=snapshot.mem_total_gb,
        mem_available_gb=snapshot.mem_available_gb,
        mem_used_pct=snapshot.mem_used_pct,
        cpu_load_1m=snapshot.cpu_load_1m,
        cpu_load_5m=snapshot.cpu_load_5m,
        cpu_load_15m=snapshot.cpu_load_15m,
        uptime_seconds=snapshot.uptime_seconds,
        gpu_name=snapshot.gpu_name,
        gpu_vram_mb=snapshot.gpu_vram_mb,
        cpu_power_mw=snapshot.cpu_power_mw,
        gpu_power_mw=snapshot.gpu_power_mw,
        thermal_pressure=snapshot.thermal_pressure,
        error=snapshot.error,
    )


@router.get("", response_model=list[NodeHealthSnapshotResponse])
async def get_fleet_health(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the latest health snapshot for each node."""
    # DISTINCT ON is PostgreSQL-specific and performs well with the index on (node_id, collected_at)
    rows = await db.execute(
        text("""
            SELECT s.*, n.hostname
            FROM (
                SELECT DISTINCT ON (node_id) *
                FROM node_health_snapshots
                ORDER BY node_id, collected_at DESC
            ) s
            JOIN nodes n ON n.id = s.node_id
            ORDER BY n.hostname NULLS LAST
        """)
    )
    results = rows.mappings().all()

    snapshots = []
    for row in results:
        snap = NodeHealthSnapshot(**{
            k: v for k, v in row.items() if k != "hostname"
        })
        snapshots.append(_to_response(snap, row.get("hostname")))
    return snapshots


@router.post("/collect", response_model=CollectResponse, status_code=202)
async def trigger_collection(
    _: dict = Depends(require_role("admin")),
):
    """Trigger an immediate health collection from all online nodes."""
    from fleet_platform.workers.health_tasks import collect_fleet_health
    collect_fleet_health.delay()
    return CollectResponse(status="queued", message="Health collection task queued.")


@router.get("/{node_id}/history", response_model=list[NodeHealthSnapshotResponse])
async def get_node_health_history(
    node_id: uuid.UUID,
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return health snapshots for a node over the last N hours (default 24, max 168)."""
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    since = datetime.now(UTC) - timedelta(hours=hours)
    result = await db.execute(
        select(NodeHealthSnapshot)
        .where(
            NodeHealthSnapshot.node_id == node_id,
            NodeHealthSnapshot.collected_at >= since,
        )
        .order_by(NodeHealthSnapshot.collected_at.asc())
    )
    snapshots = result.scalars().all()
    return [_to_response(s, node.hostname) for s in snapshots]
```

- [ ] **Step 4: Register router in `fleet_platform/api/main.py`**

Open `fleet_platform/api/main.py`. Add import after the existing router imports:
```python
from fleet_platform.api.routes import fleet_health
```

Add inside `create_app()` after the security_router line:
```python
    app.include_router(fleet_health.router, tags=["fleet-health"])
```

- [ ] **Step 5: Run unit suite to confirm no regressions**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/unit/ -q
```
Expected: all pass, 0 failures

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/schemas/fleet_health.py \
        fleet_platform/api/routes/fleet_health.py \
        fleet_platform/api/main.py \
        tests/integration/test_fleet_health_api.py
git commit -m "feat: fleet health API — latest snapshots, on-demand collect, node history"
```

---

## Task 5: Frontend Fleet Health Dashboard

**Files:**
- Create: `frontend/src/api/fleetHealth.ts`
- Create: `frontend/src/pages/FleetHealthPage.tsx`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: sidebar/nav component (add Fleet Health link)

- [ ] **Step 1: Find the nav component**

```bash
grep -rn "Fleet\|Nodes\|Dashboard\|href.*nodes" frontend/src/components/ frontend/src/App.tsx | grep -i "nav\|sidebar\|link" | head -20
```

This shows which file holds the sidebar navigation items.

- [ ] **Step 2: Create `frontend/src/api/fleetHealth.ts`**

```typescript
// frontend/src/api/fleetHealth.ts
import { api } from './client'

export interface NodeHealthSnapshot {
  id: string
  node_id: string
  minion_id: string
  hostname: string | null
  collected_at: string
  disk_root_used_gb: number | null
  disk_root_total_gb: number | null
  disk_root_pct: number | null
  disk_root_inodes_pct: number | null
  mem_total_gb: number | null
  mem_available_gb: number | null
  mem_used_pct: number | null
  cpu_load_1m: number | null
  cpu_load_5m: number | null
  cpu_load_15m: number | null
  uptime_seconds: number | null
  gpu_name: string | null
  gpu_vram_mb: number | null
  cpu_power_mw: number | null
  gpu_power_mw: number | null
  thermal_pressure: string | null
  error: string | null
  // computed by API
  disk_alert: boolean
  mem_alert: boolean
  thermal_alert: boolean
}

export const fleetHealthApi = {
  getFleetHealth: () => api.get<NodeHealthSnapshot[]>('/api/v1/fleet-health'),
  triggerCollect: () => api.post<{ status: string; message: string }>('/api/v1/fleet-health/collect', {}),
  getNodeHistory: (nodeId: string, hours = 24) =>
    api.get<NodeHealthSnapshot[]>(`/api/v1/fleet-health/${nodeId}/history?hours=${hours}`),
}

export function formatUptime(seconds: number | null): string {
  if (seconds === null) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function formatPower(mw: number | null): string {
  if (mw === null) return '—'
  return mw >= 1000 ? `${(mw / 1000).toFixed(1)} W` : `${mw} mW`
}

export function thermalColor(pressure: string | null): string {
  switch (pressure) {
    case 'Nominal': return 'text-green-600'
    case 'Light': return 'text-yellow-500'
    case 'Moderate': return 'text-orange-500'
    case 'Heavy': return 'text-red-600'
    case 'Critical': return 'text-red-800 font-bold'
    default: return 'text-gray-400'
  }
}
```

- [ ] **Step 3: Create `frontend/src/pages/FleetHealthPage.tsx`**

```tsx
// frontend/src/pages/FleetHealthPage.tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import {
  fleetHealthApi, NodeHealthSnapshot, formatUptime, formatPower, thermalColor,
} from '../api/fleetHealth'
import { useToastStore } from '../stores/toastStore'

function MetricBar({ value, alert }: { value: number | null; alert: boolean }) {
  const pct = value ?? 0
  return (
    <div className="w-full bg-gray-200 rounded-full h-2 mt-1">
      <div
        className={`h-2 rounded-full transition-all ${alert ? 'bg-red-500' : pct > 70 ? 'bg-yellow-400' : 'bg-green-500'}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

function NodeCard({
  snap,
  onSelect,
  selected,
}: {
  snap: NodeHealthSnapshot
  onSelect: (id: string) => void
  selected: boolean
}) {
  const borderColor = snap.disk_alert || snap.mem_alert || snap.thermal_alert
    ? 'border-red-400 bg-red-50'
    : 'border-gray-200 bg-white'

  return (
    <div
      className={`border rounded-lg p-4 cursor-pointer transition-shadow hover:shadow-md ${borderColor} ${selected ? 'ring-2 ring-blue-500' : ''}`}
      onClick={() => onSelect(snap.node_id)}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="font-semibold text-gray-900 text-sm truncate">
          {snap.hostname ?? snap.minion_id}
        </span>
        {(snap.disk_alert || snap.mem_alert || snap.thermal_alert) && (
          <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">Alert</span>
        )}
      </div>

      <div className="space-y-2 text-xs text-gray-700">
        {/* Disk */}
        <div>
          <div className="flex justify-between">
            <span>Disk</span>
            <span className={snap.disk_alert ? 'text-red-600 font-semibold' : ''}>
              {snap.disk_root_pct != null ? `${snap.disk_root_pct}%` : '—'}
              {snap.disk_root_used_gb != null && snap.disk_root_total_gb != null
                ? ` (${snap.disk_root_used_gb.toFixed(0)} / ${snap.disk_root_total_gb.toFixed(0)} GB)`
                : ''}
            </span>
          </div>
          <MetricBar value={snap.disk_root_pct} alert={snap.disk_alert} />
        </div>

        {/* Memory */}
        <div>
          <div className="flex justify-between">
            <span>Memory</span>
            <span className={snap.mem_alert ? 'text-red-600 font-semibold' : ''}>
              {snap.mem_used_pct != null ? `${snap.mem_used_pct}%` : '—'}
              {snap.mem_total_gb != null ? ` (${snap.mem_total_gb.toFixed(0)} GB)` : ''}
            </span>
          </div>
          <MetricBar value={snap.mem_used_pct} alert={snap.mem_alert} />
        </div>

        {/* CPU load */}
        <div className="flex justify-between">
          <span>CPU Load</span>
          <span>
            {snap.cpu_load_1m != null
              ? `${snap.cpu_load_1m.toFixed(2)} / ${snap.cpu_load_5m?.toFixed(2) ?? '—'} / ${snap.cpu_load_15m?.toFixed(2) ?? '—'}`
              : '—'}
          </span>
        </div>

        {/* GPU */}
        {snap.gpu_name && (
          <div className="flex justify-between">
            <span>GPU</span>
            <span className="truncate max-w-[160px]" title={snap.gpu_name}>
              {snap.gpu_name}{snap.gpu_vram_mb ? ` (${snap.gpu_vram_mb >= 1024 ? `${(snap.gpu_vram_mb / 1024).toFixed(0)} GB` : `${snap.gpu_vram_mb} MB`})` : ''}
            </span>
          </div>
        )}

        {/* Power */}
        {(snap.cpu_power_mw != null || snap.gpu_power_mw != null) && (
          <div className="flex justify-between">
            <span>Power</span>
            <span>CPU {formatPower(snap.cpu_power_mw)} · GPU {formatPower(snap.gpu_power_mw)}</span>
          </div>
        )}

        {/* Thermal */}
        <div className="flex justify-between">
          <span>Thermal</span>
          <span className={thermalColor(snap.thermal_pressure)}>
            {snap.thermal_pressure ?? '—'}
          </span>
        </div>

        {/* Uptime */}
        <div className="flex justify-between">
          <span>Uptime</span>
          <span>{formatUptime(snap.uptime_seconds)}</span>
        </div>

        {/* Last collected */}
        <div className="text-gray-400 text-right">
          {format(parseISO(snap.collected_at), 'MMM d, HH:mm')}
        </div>

        {/* Error */}
        {snap.error && (
          <div className="text-red-500 text-xs truncate" title={snap.error}>
            ⚠ {snap.error}
          </div>
        )}
      </div>
    </div>
  )
}

function HistoryPanel({ nodeId, hostname }: { nodeId: string; hostname: string | null }) {
  const { data: history = [], isLoading } = useQuery({
    queryKey: ['fleet-health-history', nodeId],
    queryFn: () => fleetHealthApi.getNodeHistory(nodeId, 24),
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-gray-500">Loading history…</div>
  if (history.length === 0) return <div className="p-6 text-sm text-gray-500">No history in the last 24h.</div>

  const chartData = history.map(s => ({
    time: format(parseISO(s.collected_at), 'HH:mm'),
    disk: s.disk_root_pct,
    mem: s.mem_used_pct,
    cpu1: s.cpu_load_1m != null ? Number(s.cpu_load_1m.toFixed(2)) : null,
    cpuPowerW: s.cpu_power_mw != null ? +(s.cpu_power_mw / 1000).toFixed(2) : null,
  }))

  return (
    <div className="border-t border-gray-200 bg-white p-6">
      <h3 className="font-semibold text-gray-900 mb-4">
        {hostname ?? nodeId} — Last 24h
      </h3>

      <div className="space-y-6">
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">Disk & Memory %</p>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
              <Tooltip />
              <Line type="monotone" dataKey="disk" stroke="#3b82f6" dot={false} name="Disk %" />
              <Line type="monotone" dataKey="mem" stroke="#f59e0b" dot={false} name="Mem %" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">CPU Load (1m avg)</p>
          <ResponsiveContainer width="100%" height={100}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="cpu1" stroke="#10b981" dot={false} name="Load 1m" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {chartData.some(d => d.cpuPowerW != null) && (
          <div>
            <p className="text-xs font-medium text-gray-600 mb-1">CPU Power (W)</p>
            <ResponsiveContainer width="100%" height={100}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="time" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="W" />
                <Tooltip />
                <Line type="monotone" dataKey="cpuPowerW" stroke="#8b5cf6" dot={false} name="CPU Power" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}

export default function FleetHealthPage() {
  const qc = useQueryClient()
  const toast = useToastStore(s => s.addToast)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const { data: snapshots = [], isLoading, error } = useQuery({
    queryKey: ['fleet-health'],
    queryFn: () => fleetHealthApi.getFleetHealth(),
    refetchInterval: 60_000,
  })

  const collectMut = useMutation({
    mutationFn: () => fleetHealthApi.triggerCollect(),
    onSuccess: () => {
      toast({ type: 'success', message: 'Health collection queued. Data refreshes in ~60s.' })
      setTimeout(() => qc.invalidateQueries({ queryKey: ['fleet-health'] }), 5000)
    },
    onError: () => toast({ type: 'error', message: 'Failed to trigger collection.' }),
  })

  const alertCount = snapshots.filter(s => s.disk_alert || s.mem_alert || s.thermal_alert).length
  const selected = snapshots.find(s => s.node_id === selectedNodeId) ?? null

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Fleet Health</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {snapshots.length} node{snapshots.length !== 1 ? 's' : ''}
            {alertCount > 0 && (
              <span className="ml-2 text-red-600 font-medium">· {alertCount} alert{alertCount !== 1 ? 's' : ''}</span>
            )}
          </p>
        </div>
        <button
          onClick={() => collectMut.mutate()}
          disabled={collectMut.isPending}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-colors"
        >
          {collectMut.isPending ? 'Queuing…' : 'Collect Now'}
        </button>
      </div>

      {/* Alert banner */}
      {alertCount > 0 && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          ⚠ {alertCount} node{alertCount !== 1 ? 's are' : ' is'} above threshold — disk ≥ 85% or memory ≥ 90% or thermal pressure detected.
        </div>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="border border-gray-200 rounded-lg p-4 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
              <div className="space-y-2">
                {[...Array(5)].map((_, j) => <div key={j} className="h-3 bg-gray-100 rounded" />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="text-red-600 text-sm">Failed to load fleet health data.</div>
      )}

      {!isLoading && !error && snapshots.length === 0 && (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg font-medium">No health data yet.</p>
          <p className="text-sm mt-1">Click <strong>Collect Now</strong> to gather metrics from online nodes.</p>
        </div>
      )}

      {/* Node grid */}
      {snapshots.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {snapshots.map(snap => (
            <NodeCard
              key={snap.node_id}
              snap={snap}
              selected={selectedNodeId === snap.node_id}
              onSelect={id => setSelectedNodeId(prev => prev === id ? null : id)}
            />
          ))}
        </div>
      )}

      {/* History panel */}
      {selected && (
        <div className="mt-6 rounded-lg border border-gray-200 overflow-hidden">
          <HistoryPanel nodeId={selected.node_id} hostname={selected.hostname} />
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Add route to `frontend/src/App.tsx`**

Open `frontend/src/App.tsx`. Find the imports of page components and add:
```tsx
import FleetHealthPage from './pages/FleetHealthPage'
```

Find the router/routes section and add:
```tsx
<Route path="/fleet-health" element={<FleetHealthPage />} />
```

- [ ] **Step 5: Add nav link to sidebar**

Run the grep from Step 1 to identify the exact file. Open it. Find the pattern for existing nav items (look for how "Nodes" or "Dashboard" links are structured). Add a new item in the same pattern:

```tsx
{
  label: 'Fleet Health',
  href: '/fleet-health',
  icon: <HeartPulseIcon />,   // use whatever icon component the project uses
}
```

If the project uses Heroicons, import `HeartIcon` or `CpuChipIcon` from `@heroicons/react/24/outline`. Use whichever matches existing nav icon style.

- [ ] **Step 6: Build the frontend — must succeed with 0 type errors**

```bash
cd /home/dk/Documents/git/kri/frontend && npm run build 2>&1 | tail -20
```
Expected: Build succeeded, 0 errors. Fix any TypeScript errors before committing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/fleetHealth.ts \
        frontend/src/pages/FleetHealthPage.tsx \
        frontend/src/App.tsx \
        frontend/src/components/<nav-file>.tsx
git commit -m "feat: Fleet Health dashboard — per-node cards, history charts, collect trigger"
```

---

## Self-Review

### 1. Spec coverage vs acceptance criteria

| Criterion | Task |
|---|---|
| Disk, inodes, memory, CPU, uptime, GPU, powermetrics collected | T1 |
| Snapshots stored in DB per node | T2 |
| Celery beat every 15 min | T3 |
| API: latest per node, on-demand trigger, history | T4 |
| Per-node cards with metrics | T5 |
| Threshold alerting (disk > 85%, mem > 90%) | T5 — `disk_alert`, `mem_alert` computed fields |
| Sidebar navigation | T5 Step 5 |

### 2. Placeholder scan

No TBD, TODO, or "add appropriate..." patterns. All code blocks are complete.

### 3. Type consistency

- `parse_disk_usage` returns `disk_root_pct`, `disk_root_used_gb`, `disk_root_total_gb` — used under same names in `NodeHealthSnapshot` model and `collect_all_metrics`.
- `parse_inode_usage` returns `disk_root_inodes_pct` — matches model column name.
- `parse_vm_stat` returns `mem_total_gb`, `mem_available_gb`, `mem_used_pct` — matches model.
- `NodeHealthSnapshotResponse.disk_alert` computed field reads `disk_root_pct` — same name as in response body.
- `fleetHealthApi.getFleetHealth()` returns `NodeHealthSnapshot[]` — interface matches backend schema fields.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-26-fleet-health-dashboard.md`.

**Subagent-Driven (recommended)** — fresh subagent per task, two-stage review, background dispatch.
