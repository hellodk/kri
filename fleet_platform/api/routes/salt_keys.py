import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, require_role

_MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

router = APIRouter(prefix="/api/v1/salt")

_PKI_BASE = Path(os.environ.get("SALT_PKI_DIR", "/etc/salt/pki/master"))


def _dirs() -> dict[str, Path]:
    return {
        "accepted": _PKI_BASE / "minions",
        "pending": _PKI_BASE / "minions_pre",
        "rejected": _PKI_BASE / "minions_rejected",
        "denied": _PKI_BASE / "minions_denied",
    }


@router.get("/keys")
async def list_keys(_: dict = Depends(get_current_user)):
    """List all minion keys grouped by status."""
    result: dict[str, list[str]] = {}
    for status, path in _dirs().items():
        try:
            result[status] = sorted(f.name for f in path.iterdir() if f.is_file()) if path.exists() else []
        except PermissionError:
            # salt-master owns the PKI dir with mode 700; the API container may not
            # have permission to traverse it right after a container restart.
            # Gracefully return an empty list so the UI shows "no keys" instead of 500.
            result[status] = []
    result["pending_count"] = len(result["pending"])  # type: ignore[assignment]
    return result


def _validate_minion_id(minion_id: str) -> None:
    if not _MINION_ID_RE.match(minion_id):
        raise HTTPException(status_code=422, detail=f"Invalid minion_id '{minion_id}'")


@router.post("/keys/{minion_id}/accept")
async def accept_key(
    minion_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Accept a pending minion key."""
    _validate_minion_id(minion_id)
    dirs = _dirs()
    src = dirs["pending"] / minion_id
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"No pending key for '{minion_id}'")
    dirs["accepted"].mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dirs["accepted"] / minion_id))
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
    """Move a pending key to rejected."""
    _validate_minion_id(minion_id)
    dirs = _dirs()
    src = dirs["pending"] / minion_id
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"No pending key for '{minion_id}'")
    dirs["rejected"].mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dirs["rejected"] / minion_id))
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
    """Delete a key from any status bucket."""
    _validate_minion_id(minion_id)
    for path in _dirs().values():
        target = path / minion_id
        if target.exists():
            target.unlink()
            await audit(
                db,
                actor=claims["email"],
                action="salt_key.delete",
                resource_type="salt_key",
                new_value={"minion_id": minion_id},
            )
            await db.commit()
            return {"status": "deleted", "minion_id": minion_id}
    raise HTTPException(status_code=404, detail=f"No key found for '{minion_id}'")
