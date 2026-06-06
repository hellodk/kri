"""Routes for SaltMaster management — issue #517, #519, #521, epic #523.

Endpoints:
    GET  /api/v1/salt/masters                     — list all masters (viewer+).
    POST /api/v1/salt/masters/{master_id}/test    — live probe (admin only).
    GET  /api/v1/salt/masters/{master_id}/health  — cached health (viewer+).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.schemas.salt_master import SaltMasterResponse
from fleet_platform.services.salt_master_probe import run_probe

router = APIRouter(prefix="/api/v1/salt")

_PROBE_TIMEOUT_SECONDS = 30


@router.get("/masters", response_model=List[SaltMasterResponse])
async def list_salt_masters(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> List[SaltMasterResponse]:
    """Return all configured SaltMasters, default first then alphabetically by name.

    Accessible by any authenticated user (viewer role or above).
    Never exposes api_password or api_password_enc.
    """
    result = await db.execute(select(SaltMaster).order_by(SaltMaster.is_default.desc(), SaltMaster.name))
    return [SaltMasterResponse.model_validate(m) for m in result.scalars().all()]


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


@router.get("/masters/{master_id}/health")
async def get_salt_master_health(
    master_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user),
):
    """Return the cached health status for a SaltMaster row.

    Reads the persisted ``status``, ``last_checked_at``, ``last_error``,
    and ``checks`` fields written by the ``poll_salt_masters`` beat task
    (#519).  Never makes a live salt-api or probe call — the response is
    always served from the DB cache so the request cannot block on an
    unreachable master.

    Returns 404 if the master does not exist.
    Accessible by any authenticated user (viewer role or above).
    """
    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    return {
        "id": str(master.id),
        "name": master.name,
        "status": master.status,
        "last_checked_at": master.last_checked_at.isoformat() if master.last_checked_at else None,
        "last_error": master.last_error,
        "checks": master.checks,
    }
