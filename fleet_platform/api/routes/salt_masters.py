"""Routes for SaltMaster management — issue #517, epic #523.

Currently exposes a single endpoint:
    POST /api/v1/salt/masters/{master_id}/test  — probe a master's prerequisites.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.salt_master_probe import run_probe

router = APIRouter(prefix="/api/v1/salt")

_PROBE_TIMEOUT_SECONDS = 30


@router.post("/masters/{master_id}/test")
async def test_salt_master(
    master_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Probe a salt-master's prerequisites and return per-check results.

    Runs all connectivity and capability checks (DNS, TCP, salt-api auth,
    key store, version, minion count, token delivery) against the master
    identified by *master_id*.

    Persists the result to the master row (status, last_checked_at,
    last_error, checks) before returning.

    Returns 404 if the master does not exist.
    Requires admin role.
    """
    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    try:
        probe_result = await asyncio.wait_for(
            run_probe(master),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        probe_result = {
            "status": "unreachable",
            "checks": [
                {
                    "check": "probe",
                    "status": "fail",
                    "detail": f"Probe timed out after {_PROBE_TIMEOUT_SECONDS}s",
                    "latency_ms": _PROBE_TIMEOUT_SECONDS * 1000,
                }
            ],
        }

    # Persist results to the master row
    master.status = probe_result["status"]
    master.last_checked_at = datetime.now(UTC)
    failed_checks = [c for c in probe_result["checks"] if c["status"] == "fail"]
    master.last_error = failed_checks[0]["detail"] if failed_checks else None
    master.checks = probe_result["checks"]  # type: ignore[assignment]

    await db.commit()

    return probe_result
