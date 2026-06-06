"""Salt key management via salt-api wheel client — epic #523, issue #518.

Removes PKI-filesystem reads; all key operations are routed through the
default SaltMaster's salt-api (rest_cherrypy) using the wheel client.
"""

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.salt_api_client import SaltApiError, run_wheel

_MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

router = APIRouter(prefix="/api/v1/salt")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEGRADED_NO_MASTER: dict[str, Any] = {
    "accepted": [],
    "pending": [],
    "rejected": [],
    "denied": [],
    "pending_count": 0,
    "degraded": True,
    "degraded_reason": "No salt-master configured",
}


def _empty_degraded(reason: str) -> dict[str, Any]:
    return {
        "accepted": [],
        "pending": [],
        "rejected": [],
        "denied": [],
        "pending_count": 0,
        "degraded": True,
        "degraded_reason": reason,
    }


async def _get_default_master(db: AsyncSession) -> SaltMaster | None:
    result = await db.execute(select(SaltMaster).where(SaltMaster.is_default.is_(True)))
    return result.scalars().first()


def _validate_minion_id(minion_id: str) -> None:
    if not _MINION_ID_RE.match(minion_id):
        raise HTTPException(status_code=422, detail=f"Invalid minion_id '{minion_id}'")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/keys")
async def list_keys(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List all minion keys grouped by status via salt-api wheel client."""
    master = await _get_default_master(db)
    if master is None:
        return _DEGRADED_NO_MASTER

    try:
        data = run_wheel(master, "key.list_all")
    except SaltApiError as exc:
        return _empty_degraded(exc.reason)

    return {
        "accepted": sorted(data.get("minions", [])),
        "pending": sorted(data.get("minions_pre", [])),
        "rejected": sorted(data.get("minions_rejected", [])),
        "denied": sorted(data.get("minions_denied", [])),
        "pending_count": len(data.get("minions_pre", [])),
        "degraded": False,
        "degraded_reason": None,
    }


@router.post("/keys/{minion_id}/accept")
async def accept_key(
    minion_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Accept a pending minion key via salt-api wheel client."""
    _validate_minion_id(minion_id)

    master = await _get_default_master(db)
    if master is None:
        raise HTTPException(status_code=503, detail="No salt-master configured")

    try:
        run_wheel(master, "key.accept", match=minion_id)
    except SaltApiError as exc:
        raise HTTPException(status_code=502, detail=exc.reason) from exc

    await audit(
        db,
        actor=claims["email"],
        action="salt_key.accept",
        resource_type="salt_key",
        new_value={"minion_id": minion_id},
    )
    await db.commit()
    return {"status": "accepted", "minion_id": minion_id}


@router.post("/keys/{minion_id}/reject")
async def reject_key(
    minion_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Reject a minion key via salt-api wheel client."""
    _validate_minion_id(minion_id)

    master = await _get_default_master(db)
    if master is None:
        raise HTTPException(status_code=503, detail="No salt-master configured")

    try:
        run_wheel(master, "key.reject", match=minion_id)
    except SaltApiError as exc:
        raise HTTPException(status_code=502, detail=exc.reason) from exc

    await audit(
        db,
        actor=claims["email"],
        action="salt_key.reject",
        resource_type="salt_key",
        new_value={"minion_id": minion_id},
    )
    await db.commit()
    return {"status": "rejected", "minion_id": minion_id}


@router.delete("/keys/{minion_id}")
async def delete_key(
    minion_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Delete a minion key via salt-api wheel client."""
    _validate_minion_id(minion_id)

    master = await _get_default_master(db)
    if master is None:
        raise HTTPException(status_code=503, detail="No salt-master configured")

    try:
        run_wheel(master, "key.delete", match=minion_id)
    except SaltApiError as exc:
        raise HTTPException(status_code=502, detail=exc.reason) from exc

    await audit(
        db,
        actor=claims["email"],
        action="salt_key.delete",
        resource_type="salt_key",
        new_value={"minion_id": minion_id},
    )
    await db.commit()
    return {"status": "deleted", "minion_id": minion_id}
