"""Routes for SaltMaster management — issue #517, #519, #521, #533, epic #523, #537.

Provision lifecycle SSH cred encryption added in #556 (master-lifecycle epic).
SSoT api_url derivation added in #562: api_url is computed from address + salt_api_port +
use_tls on every create/update.  Client-supplied api_url is always ignored.
provision_master trigger route added in #557 (master-lifecycle epic).
provision-status read endpoint added in #558 (master-lifecycle epic phase 3).
minions topology endpoint added in #560 (master-lifecycle epic phase 5).

Endpoints:
    GET    /api/v1/salt/masters                              — list all masters (viewer+).
    POST   /api/v1/salt/masters                              — create master (admin only).
    PATCH  /api/v1/salt/masters/{master_id}                  — update master (admin only).
    DELETE /api/v1/salt/masters/{master_id}                  — delete master (admin only).
    POST   /api/v1/salt/masters/{master_id}/test             — live probe (admin only).
    GET    /api/v1/salt/masters/{master_id}/health           — cached health (viewer+).
    POST   /api/v1/salt/masters/{master_id}/provision        — trigger provision task (admin only).
    GET    /api/v1/salt/masters/{master_id}/provision-status — latest provision run (viewer+).
    GET    /api/v1/salt/masters/{master_id}/minions          — nodes using this master (viewer+).
    POST   /api/v1/salt/masters/{master_id}/attach-minions   — re-point minions at this master, additively (admin only).

attach-minions added in #977 (master-promotion Phase C): re-points selected
minions at a master additively (HA) — the minion's rendered config gains the
target master alongside its current one; Node.salt_master_id (single-FK
ownership) moves to the target. See reconfigure_minions in ansible_tasks.py.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.master_provision_run import MasterProvisionRun
from fleet_platform.models.node import Node
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.schemas.fleet import NodeListItem
from fleet_platform.schemas.salt_master import (
    MasterProvisionRunResponse,
    SaltMasterCreate,
    SaltMasterResponse,
    SaltMasterUpdate,
)
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


async def _assert_master_identity_unique(
    db: AsyncSession,
    *,
    name: str,
    address: str,
    publish_port: int,
    ret_port: int,
    salt_api_port: int,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Reject a duplicate salt-master by NAME or by network ENDPOINT (#1018).

    A master IS its endpoint (address + publish/ret/api ports), so two rows for
    the same endpoint are meaningless — that's how the 192.168.1.64 / -1 twins
    appeared. Fail loud with 409 instead of allowing a silent duplicate (endpoint)
    or raising a raw IntegrityError 500 (name).
    """
    name_stmt = select(SaltMaster).where(SaltMaster.name == name)
    if exclude_id is not None:
        name_stmt = name_stmt.where(SaltMaster.id != exclude_id)
    if (await db.execute(name_stmt)).scalars().first() is not None:
        raise HTTPException(status_code=409, detail=f"A salt-master named '{name}' already exists")

    ep_stmt = select(SaltMaster).where(
        SaltMaster.address == address,
        SaltMaster.publish_port == publish_port,
        SaltMaster.ret_port == ret_port,
        SaltMaster.salt_api_port == salt_api_port,
    )
    if exclude_id is not None:
        ep_stmt = ep_stmt.where(SaltMaster.id != exclude_id)
    dup = (await db.execute(ep_stmt)).scalars().first()
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A salt-master already exists at {address} "
                f"(ports {publish_port}/{ret_port}, api {salt_api_port}) — '{dup.name}'"
            ),
        )


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
    # Reject duplicate name or endpoint up front (#1018) — a master IS its endpoint.
    await _assert_master_identity_unique(
        db,
        name=body.name,
        address=body.address,
        publish_port=body.publish_port,
        ret_port=body.ret_port,
        salt_api_port=body.salt_api_port,
    )

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

    # Reject a name/endpoint collision introduced by this update (#1018).
    if {"name", "address", "publish_port", "ret_port", "salt_api_port"} & set(update_data):
        await _assert_master_identity_unique(
            db,
            name=master.name,
            address=master.address,
            publish_port=master.publish_port,
            ret_port=master.ret_port,
            salt_api_port=master.salt_api_port,
            exclude_id=master_id,
        )

    # Recompute api_url after all field updates — keeps SSoT consistent (#562)
    master.api_url = _derive_api_url(master.address, master.salt_api_port, master.use_tls)

    await db.commit()
    await db.refresh(master)
    return SaltMasterResponse.model_validate(master)


@router.delete("/masters/{master_id}", status_code=200)
async def delete_salt_master(
    master_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> dict:
    """Delete a SaltMaster.

    Nodes assigned to the deleted master are automatically reassigned to the
    current default master.  If no default master exists and nodes are present,
    deletion is blocked with 409.

    Invariants checked before deletion:
    - Cannot delete if it is the default master (promote another first).
    - Cannot delete if it is the only enabled master (would leave 0 enabled).
    - Cannot delete if nodes are assigned and there is no default master to
      receive them.

    Returns 404 if the master does not exist.
    Returns 409 with a clear message if an invariant is violated.
    Returns 200 with ``{"nodes_reassigned": N, "reassigned_to": name|null}``.
    Requires admin role.
    """
    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    # Invariant 0 (#579): cannot remove the DEFAULT master. Deleting it would leave
    # salt_keys._get_default_master() returning None — all key accept/list/reject
    # break and onboarding halts. Caller must promote another enabled master to
    # default (PATCH is_default=true) before deleting this one.
    if master.is_default:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete the default salt master '{master.name}'. "
                "Promote another enabled master to default first, then delete this one."
            ),
        )

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

    # Auto-reassign nodes to the default master before deletion.
    node_count_result = await db.execute(select(func.count()).select_from(Node).where(Node.salt_master_id == master_id))
    node_count = node_count_result.scalar_one()
    nodes_reassigned = 0
    reassigned_to: str | None = None

    if node_count > 0:
        default_result = await db.execute(
            select(SaltMaster).where(SaltMaster.is_default.is_(True), SaltMaster.id != master_id)
        )
        default_master = default_result.scalar_one_or_none()
        if default_master is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot delete salt master '{master.name}': {node_count} node(s) are assigned "
                    "and there is no default master to reassign them to. "
                    "Create or promote another master as default first."
                ),
            )
        await db.execute(update(Node).where(Node.salt_master_id == master_id).values(salt_master_id=default_master.id))
        nodes_reassigned = node_count
        reassigned_to = default_master.name

    await db.delete(master)
    await db.commit()
    return {"nodes_reassigned": nodes_reassigned, "reassigned_to": reassigned_to}


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
    from fleet_platform.workers.celery_app import celery_app

    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    action = (body.action if body and body.action else None) or "install"

    task = celery_app.send_task(
        "fleet_platform.workers.ansible_tasks.provision_master",
        args=[str(master_id), action],
        queue="ansible",
    )

    return {
        "task_id": task.id,
        "salt_master_id": str(master_id),
        "action": action,
        "status": "queued",
    }


@router.get("/masters/{master_id}/provision-status", response_model=Optional[MasterProvisionRunResponse])
async def get_provision_status(
    master_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> Optional[MasterProvisionRunResponse]:
    """Return the latest MasterProvisionRun for a SaltMaster, or null if none exists.

    Returns the most recent run ordered by started_at descending.
    Returns 404 if the master does not exist.
    Accessible by any authenticated user (viewer role or above).
    Added in #558 (master-lifecycle epic phase 3).
    """
    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    run_result = await db.execute(
        select(MasterProvisionRun)
        .where(MasterProvisionRun.salt_master_id == master_id)
        .order_by(MasterProvisionRun.started_at.desc())
        .limit(1)
    )
    run = run_result.scalar_one_or_none()
    if run is None:
        return None
    return MasterProvisionRunResponse.model_validate(run)


@router.get("/masters/{master_id}/minions", response_model=List[NodeListItem])
async def list_master_minions(
    master_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> List[NodeListItem]:
    """Return nodes whose ``salt_master_id`` points to this master.

    Returns an empty list when no nodes are assigned (not a 404).
    Returns 404 if the master does not exist.
    Accessible by any authenticated user (viewer role or above).
    Added in #560 (master-lifecycle epic phase 5).
    """
    master_result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    if master_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    from sqlalchemy.orm import selectinload

    nodes_result = await db.execute(
        select(Node)
        .where(Node.salt_master_id == master_id)
        .options(selectinload(Node.tags))
        .order_by(Node.hostname, Node.minion_id)
    )
    nodes = nodes_result.scalars().all()
    return [NodeListItem.model_validate(n) for n in nodes]


class AttachMinionsRequest(BaseModel):
    """Body for the attach-minions endpoint — node ids to re-point at this master."""

    node_ids: List[str]


@router.post("/masters/{master_id}/attach-minions", status_code=202)
async def attach_minions(
    master_id: uuid.UUID,
    body: AttachMinionsRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    """Re-point selected minions at ``master_id``, additively (#977, Phase C).

    Enqueues ``reconfigure_minions`` which builds the additive ``salt_masters``
    list per node (current master's address + this master's address, deduped),
    re-renders the minion config, restarts the service, accepts the minion's
    key on this master, and moves ``Node.salt_master_id`` (single-FK ownership)
    to this master. The task runs asynchronously; the caller receives 202.

    Returns 404 if the master does not exist, 422 if ``node_ids`` is empty.
    Requires admin role.
    """
    from fleet_platform.workers.celery_app import celery_app

    result = await db.execute(select(SaltMaster).where(SaltMaster.id == master_id))
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail=f"SaltMaster {master_id} not found")

    if not body.node_ids:
        raise HTTPException(status_code=422, detail="node_ids must not be empty")

    celery_app.send_task(
        "fleet_platform.workers.ansible_tasks.reconfigure_minions",
        args=[str(master_id), body.node_ids],
        queue="ansible",
    )

    return {
        "status": "queued",
        "master_id": str(master_id),
        "count": len(body.node_ids),
    }
