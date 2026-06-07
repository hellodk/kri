"""Routes for SaltMaster management — issue #517, #519, #521, #533, epic #523, #537.

Provision lifecycle SSH cred encryption added in #556 (master-lifecycle epic).
SSoT api_url derivation added in #562: api_url is computed from address + salt_api_port +
use_tls on every create/update.  Client-supplied api_url is always ignored.
provision_master trigger route added in #557 (master-lifecycle epic).

Endpoints:
    GET    /api/v1/salt/masters                     — list all masters (viewer+).
    POST   /api/v1/salt/masters                     — create master (admin only).
    PATCH  /api/v1/salt/masters/{master_id}         — update master (admin only).
    DELETE /api/v1/salt/masters/{master_id}         — delete master (admin only).
    POST   /api/v1/salt/masters/{master_id}/test    — live probe (admin only).
    GET    /api/v1/salt/masters/{master_id}/health  — cached health (viewer+).
    POST   /api/v1/salt/masters/{master_id}/provision — trigger provision task (admin only).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.node import Node
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.schemas.salt_master import SaltMasterCreate, SaltMasterResponse, SaltMasterUpdate
from fleet_platform.services.platform_settings_svc import encrypt_secret
from fleet_platform.services.salt_master_probe import run_probe

router = APIRouter(prefix="/api/v1/salt")

_PROBE_TIMEOUT_SECONDS = 30


def _derive_api_url(address: str, salt_api_port: int, use_tls: bool) -> str:
    """Compute api_url from the SSoT fields — the single source of truth (#562)."""
    scheme = "https" if use_tls else "http"
    return f"{scheme}://{address}:{salt_api_port}"


@router.get("/masters", response_model=List[SaltMasterResponse])
async def list_salt_masters(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> List[SaltMasterResponse]:
    """Return all configured SaltMasters, default first then alphabetically by name.

    Accessible by any authenticated user (viewer role or above).
    Never exposes api_password, ssh_key_enc, or ssh_password_enc.
    """
    result = await db.execute(select(SaltMaster).order_by(SaltMaster.is_default.desc(), SaltMaster.name))
    return [SaltMasterResponse.model_validate(m) for m in result.scalars().all()]


@router.post("/masters", response_model=SaltMasterResponse, status_code=201)
async def create_salt_master(
    body: SaltMasterCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> SaltMasterResponse:
    """Create a new SaltMaster.

    If ``api_password`` is provided it is encrypted at rest; the plaintext is
    never persisted.  SSH credentials (``ssh_key``, ``ssh_password``) are likewise
    encrypted if provided.  If ``is_default=True`` all other masters are cleared
    first.  Requires admin role.
    """
    # If setting as default, clear is_default on all existing masters first.
    if body.is_default:
        existing = await db.execute(select(SaltMaster).where(SaltMaster.is_default.is_(True)))
        for m in existing.scalars().all():
            m.is_default = False

    api_password_enc: str | None = None
    if body.api_password:
        api_password_enc = encrypt_secret(body.api_password)

    ssh_key_enc: str | None = None
    if body.ssh_key:
        ssh_key_enc = encrypt_secret(body.ssh_key)

    ssh_password_enc: str | None = None
    if body.ssh_password:
        ssh_password_enc = encrypt_secret(body.ssh_password)

    # Derive api_url from SSoT fields — any client-supplied api_url is ignored (#562)
    derived_api_url = _derive_api_url(body.address, body.salt_api_port, body.use_tls)

    master = SaltMaster(
        name=body.name,
        address=body.address,
        enabled=body.enabled,
        is_default=body.is_default,
        publish_port=body.publish_port,
        ret_port=body.ret_port,
        salt_api_port=body.salt_api_port,
        use_tls=body.use_tls,
        # control_mode / api_eauth / token_delivery use ORM defaults (server-side)
        api_url=derived_api_url,
        api_user=body.api_user,
        api_password_enc=api_password_enc,
        api_eauth="pam",  # server-side default; not user-editable
        tls_verify=body.tls_verify,
        auto_accept=body.auto_accept,
        ssh_host=body.ssh_host,
        ssh_user=body.ssh_user,
        ssh_key_enc=ssh_key_enc,
        ssh_password_enc=ssh_password_enc,
        node_id=body.node_id,
    )
    db.add(master)
    await db.commit()
    await db.refresh(master)
    return SaltMasterResponse.model_validate(master)


@router.patch("/masters/{master_id}", response_model=SaltMasterResponse)
async def update_salt_master(
    master_id: uuid.UUID,
    body: SaltMasterUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> SaltMasterResponse:
    """Partially update a SaltMaster.

    Only fields explicitly provided (non-None) are applied.  ``api_password``,
    ``ssh_key``, and ``ssh_password`` are re-encrypted if provided.  Setting
    ``enabled=False`` on the last enabled master raises 409.  Setting
    ``is_default=True`` clears the flag on all other masters.  Returns 404 if
    the master does not exist.  Requires admin role.
    """
    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    update_data = body.model_dump(exclude_unset=True)

    # Drop any client-supplied api_url — it is always derived (#562)
    update_data.pop("api_url", None)

    # Guard: disabling the last enabled master is not allowed.
    if update_data.get("enabled") is False and master.enabled:
        count_result = await db.execute(
            select(func.count()).select_from(SaltMaster).where(SaltMaster.enabled.is_(True))
        )
        enabled_count = count_result.scalar_one()
        if enabled_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot disable the last enabled salt master — at least one must remain enabled.",
            )

    # Handle is_default promotion — clear flag on all other masters first.
    if update_data.get("is_default") is True and not master.is_default:
        others = await db.execute(select(SaltMaster).where(SaltMaster.is_default.is_(True), SaltMaster.id != master_id))
        for m in others.scalars().all():
            m.is_default = False

    # Re-encrypt api_password if provided.
    if "api_password" in update_data:
        raw = update_data.pop("api_password")
        update_data["api_password_enc"] = encrypt_secret(raw) if raw else None

    # Re-encrypt SSH key if provided.
    if "ssh_key" in update_data:
        raw = update_data.pop("ssh_key")
        update_data["ssh_key_enc"] = encrypt_secret(raw) if raw else None

    # Re-encrypt SSH password if provided.
    if "ssh_password" in update_data:
        raw = update_data.pop("ssh_password")
        update_data["ssh_password_enc"] = encrypt_secret(raw) if raw else None

    for field, value in update_data.items():
        setattr(master, field, value)

    # Recompute api_url after all field updates — keeps SSoT consistent (#562)
    master.api_url = _derive_api_url(master.address, master.salt_api_port, master.use_tls)

    await db.commit()
    await db.refresh(master)
    return SaltMasterResponse.model_validate(master)


@router.delete("/masters/{master_id}", status_code=204)
async def delete_salt_master(
    master_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> None:
    """Delete a SaltMaster.

    Invariants checked before deletion:
    - Cannot delete if it is the only enabled master (would leave 0 enabled).
    - Cannot delete if any nodes reference this master via ``salt_master_id``
      (operator must reassign the nodes first).

    Returns 404 if the master does not exist.
    Returns 409 with a clear message if an invariant is violated.
    Requires admin role.
    """
    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    # Invariant 1: cannot remove the last enabled master.
    if master.enabled:
        count_result = await db.execute(
            select(func.count()).select_from(SaltMaster).where(SaltMaster.enabled.is_(True))
        )
        enabled_count = count_result.scalar_one()
        if enabled_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete the last enabled salt master — at least one must remain enabled.",
            )

    # Invariant 2: cannot remove a master that nodes are still assigned to.
    node_count_result = await db.execute(select(func.count()).select_from(Node).where(Node.salt_master_id == master_id))
    node_count = node_count_result.scalar_one()
    if node_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete salt master '{master.name}': {node_count} node(s) are still assigned to it. "
                "Reassign the nodes to a different master first."
            ),
        )

    await db.delete(master)
    await db.commit()


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


class ProvisionRequest(BaseModel):
    """Optional body for the provision endpoint."""

    action: Optional[str] = "install"


@router.post("/masters/{master_id}/provision", status_code=202)
async def trigger_provision_master(
    master_id: uuid.UUID,
    body: Optional[ProvisionRequest] = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    """Trigger a provision_master Celery task for a SaltMaster.

    Installs or reconfigures salt-master + salt-api on the master's SSH host.
    The task runs asynchronously; the caller receives 202 with the task/run id.
    Returns 404 if the master does not exist.
    Requires admin role.
    """
    from fleet_platform.workers.ansible_tasks import provision_master

    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    action = (body.action if body and body.action else None) or "install"

    task = provision_master.delay(str(master_id), action)

    return {
        "task_id": task.id,
        "salt_master_id": str(master_id),
        "action": action,
        "status": "queued",
    }
