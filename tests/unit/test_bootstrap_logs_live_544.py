"""Tests for #544: live bootstrap log polling + AnsiText render + 5-second flush.

Covers:
  1. _LOG_BATCH_INTERVAL <= 5 (backend flush reduced for live tailing)
  2. bootstrapRefetchInterval TS helper — pure function tested via node
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_bootstrap_refetch_harness.ts"
HELPER = ROOT / "frontend/src/lib/bootstrapRefetchInterval.ts"


# ---------------------------------------------------------------------------
# 1. Python constant
# ---------------------------------------------------------------------------


def test_log_batch_interval_is_5_or_less():
    """_LOG_BATCH_INTERVAL must be <= 5 seconds for live log tailing (#544)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ansible_tasks",
        str(ROOT / "fleet_platform/workers/ansible_tasks.py"),
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    # We only need the module-level constant — skip heavy Celery/DB imports.
    # Patch the problematic imports before exec.
    import sys
    import types

    _stubs = {}
    for name in [
        "celery",
        "celery.utils.log",
        "sqlalchemy",
        "sqlalchemy.orm",
        "fleet_platform",
        "fleet_platform.database",
        "fleet_platform.models",
        "fleet_platform.models.node",
        "fleet_platform.models.playbook",
        "fleet_platform.workers",
        "fleet_platform.workers.celery_app",
    ]:
        if name not in sys.modules:
            _stubs[name] = types.ModuleType(name)
            sys.modules[name] = _stubs[name]

    # Provide minimal stubs to survive module-level code
    import unittest.mock as mock

    with mock.patch.dict(
        sys.modules,
        {
            "celery": mock.MagicMock(),
            "celery.utils.log": mock.MagicMock(),
            "fleet_platform.database": mock.MagicMock(),
            "fleet_platform.models.node": mock.MagicMock(),
            "fleet_platform.models.playbook": mock.MagicMock(),
            "fleet_platform.workers.celery_app": mock.MagicMock(),
        },
    ):
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            interval = mod._LOG_BATCH_INTERVAL
        except Exception:
            # If the module can't execute due to side-effects, read the constant from source
            text = (ROOT / "fleet_platform/workers/ansible_tasks.py").read_text()
            import re

            m = re.search(r"^_LOG_BATCH_INTERVAL\s*=\s*(\d+)", text, re.MULTILINE)
            assert m is not None, "_LOG_BATCH_INTERVAL not found in ansible_tasks.py"
            interval = int(m.group(1))

    assert interval <= 5, f"_LOG_BATCH_INTERVAL is {interval}s — must be <=5 for live log tailing (#544)"


# ---------------------------------------------------------------------------
# 2. TypeScript helper via node
# ---------------------------------------------------------------------------

# (description, status_input, expected_result)
REFETCH_CASES = [
    ("bootstrapping_returns_3000", "bootstrapping", 3000),
    ("pending_returns_false", "pending", False),
    ("done_returns_false", "done", False),
    ("failed_returns_false", "failed", False),
    ("none_returns_false", None, False),
    ("empty_string_returns_false", "", False),
    ("unknown_status_returns_false", "unknown", False),
]


@pytest.fixture(scope="module")
def refetch_results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not HELPER.exists():
        pytest.skip(f"helper not found: {HELPER}")

    statuses = [c[1] for c in REFETCH_CASES]
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(HARNESS), json.dumps(statuses)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("desc,status,expected", REFETCH_CASES)
def test_bootstrap_refetch_interval(desc, status, expected, refetch_results):
    idx = [c[0] for c in REFETCH_CASES].index(desc)
    result = refetch_results[idx]
    assert result == expected, f"[{desc}] expected {expected!r}, got {result!r}"
