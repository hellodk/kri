"""Unit tests for issue #558 — GET /provision-status endpoint + provisionRefetchInterval helper.

Tests cover:
- GET /provision-status returns the latest MasterProvisionRun for a master
- GET /provision-status returns null (200) when no run exists
- GET /provision-status requires authentication (get_current_user)
- GET /provision-status is registered on the router
- provisionRefetchInterval TS helper — pure function tested via node
"""

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_provision_polling_harness.ts"
HELPER = ROOT / "frontend/src/lib/provisionPolling.ts"


# ---------------------------------------------------------------------------
# 1. Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    def test_provision_status_route_exists(self):
        """GET /masters/{id}/provision-status must be registered in the router."""
        from fleet_platform.api.routes.salt_masters import router

        routes = [r.path for r in router.routes]
        provision_status_paths = [p for p in routes if "provision-status" in p]
        assert provision_status_paths, f"No /provision-status route found in router. Routes: {routes}"

    def test_provision_status_route_is_get(self):
        """The provision-status route must be a GET method."""
        from fleet_platform.api.routes.salt_masters import router

        for route in router.routes:
            if hasattr(route, "path") and "provision-status" in route.path:
                assert "GET" in route.methods, f"Expected GET on provision-status route, got {route.methods}"
                break
        else:
            pytest.fail("provision-status route not found in router")

    def test_provision_status_uses_get_current_user(self):
        """provision-status must use get_current_user (viewer-accessible, not admin-only)."""
        import inspect

        import pytest
        from fastapi import params as fa_params

        from fleet_platform.api.routes.salt_masters import get_provision_status
        from fleet_platform.core.auth import get_current_user

        sig = inspect.signature(get_provision_status)
        deps = [p.default.dependency for p in sig.parameters.values() if isinstance(p.default, fa_params.Depends)]
        assert get_current_user in deps, "get_provision_status must use get_current_user (viewer-accessible)"
        # Must NOT gate on a specific role — verify no Depends is a require_role closure
        for dep in deps:
            if getattr(dep, "__qualname__", "").endswith("require_role.<locals>.dependency"):
                pytest.fail("get_provision_status must NOT use require_role — it is viewer-accessible")


# ---------------------------------------------------------------------------
# 2. Returns latest run
# ---------------------------------------------------------------------------


class TestProvisionStatusEndpoint:
    def _make_run(self, **kwargs):
        """Return a MagicMock MasterProvisionRun row."""
        from datetime import UTC, datetime

        run = MagicMock()
        run.id = kwargs.get("id", uuid.uuid4())
        run.salt_master_id = kwargs.get("salt_master_id", uuid.uuid4())
        run.action = kwargs.get("action", "install")
        run.status = kwargs.get("status", "completed")
        run.started_at = kwargs.get("started_at", datetime.now(UTC))
        run.finished_at = kwargs.get("finished_at", None)
        run.ansible_stdout = kwargs.get("ansible_stdout", "PLAY [all] ****\nok: [host]")
        run.error = kwargs.get("error", None)
        return run

    def test_returns_latest_run_when_exists(self):
        """When a MasterProvisionRun exists, endpoint returns it as MasterProvisionRunResponse."""
        import asyncio

        from fleet_platform.api.routes.salt_masters import get_provision_status

        master_id = uuid.uuid4()
        run = self._make_run(salt_master_id=master_id, status="completed")

        master_mock = MagicMock()

        # Simulate two db.execute calls: one for master, one for run
        db = AsyncMock()

        call_count = [0]

        async def _execute_side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # First call: master lookup
                result.scalar_one_or_none.return_value = master_mock
            else:
                # Second call: MasterProvisionRun lookup
                result.scalar_one_or_none.return_value = run
            return result

        db.execute.side_effect = _execute_side_effect

        async def _run():
            return await get_provision_status(master_id=master_id, db=db, _={})

        result = asyncio.run(_run())
        assert result is not None
        assert result.status == "completed"
        assert result.salt_master_id == run.salt_master_id

    def test_returns_none_when_no_run_exists(self):
        """When no MasterProvisionRun exists for the master, endpoint returns None."""
        import asyncio

        from fleet_platform.api.routes.salt_masters import get_provision_status

        master_id = uuid.uuid4()
        master_mock = MagicMock()

        db = AsyncMock()
        call_count = [0]

        async def _execute_side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = master_mock
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db.execute.side_effect = _execute_side_effect

        async def _run():
            return await get_provision_status(master_id=master_id, db=db, _={})

        result = asyncio.run(_run())
        assert result is None

    def test_raises_404_for_unknown_master(self):
        """When the master does not exist, endpoint raises HTTPException(404)."""
        import asyncio

        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import get_provision_status

        master_id = uuid.uuid4()
        db = AsyncMock()

        async def _execute_side_effect(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        db.execute.side_effect = _execute_side_effect

        async def _run():
            return await get_provision_status(master_id=master_id, db=db, _={})

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_run())
        assert exc_info.value.status_code == 404

    def test_returns_running_run_status(self):
        """A run with status='running' is returned correctly (live polling case)."""
        import asyncio

        from fleet_platform.api.routes.salt_masters import get_provision_status

        master_id = uuid.uuid4()
        run = self._make_run(status="running", finished_at=None, ansible_stdout="Installing...\n")

        master_mock = MagicMock()
        db = AsyncMock()
        call_count = [0]

        async def _execute_side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = master_mock
            else:
                result.scalar_one_or_none.return_value = run
            return result

        db.execute.side_effect = _execute_side_effect

        async def _run():
            return await get_provision_status(master_id=master_id, db=db, _={})

        result = asyncio.run(_run())
        assert result is not None
        assert result.status == "running"
        assert result.finished_at is None


# ---------------------------------------------------------------------------
# 3. provisionRefetchInterval TS helper via node
# ---------------------------------------------------------------------------

REFETCH_CASES = [
    ("running_returns_3000", "running", 3000),
    ("completed_returns_false", "completed", False),
    ("failed_returns_false", "failed", False),
    ("none_returns_false", None, False),
    ("empty_string_returns_false", "", False),
    ("unknown_status_returns_false", "unknown", False),
    ("provisioning_returns_false", "provisioning", False),
]


@pytest.fixture(scope="module")
def provision_refetch_results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not HELPER.exists():
        pytest.skip(f"helper not found: {HELPER}")

    statuses = [c[1] for c in REFETCH_CASES]
    proc = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--no-warnings",
            str(HARNESS),
            json.dumps(statuses),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("desc,status,expected", REFETCH_CASES)
def test_provision_refetch_interval(desc, status, expected, provision_refetch_results):
    idx = [c[0] for c in REFETCH_CASES].index(desc)
    result = provision_refetch_results[idx]
    assert result == expected, f"[{desc}] expected {expected!r}, got {result!r}"
