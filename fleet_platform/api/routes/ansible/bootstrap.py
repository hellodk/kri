# fleet_platform/api/routes/ansible/bootstrap.py
"""Bootstrap-related routes: /bootstrap/..."""

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import hash_password, require_role
from fleet_platform.core.validators import MINION_ID_RE as _MINION_ID_RE
from fleet_platform.models.node import Node
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.services.bootstrap_svc import BootstrapGroupRequired, queue_node_bootstrap

from ._router import router


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=202)
@limiter.limit("10/minute")
async def bootstrap(
    request: Request,
    payload: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if not _MINION_ID_RE.match(payload.minion_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid minion_id '{payload.minion_id}': only [a-zA-Z0-9._-] allowed",
        )

    result = await db.execute(select(Node).where(Node.minion_id == payload.minion_id))
    node = result.scalar_one_or_none()

    if node and node.bootstrap_status == "bootstrapping":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Node is already being bootstrapped",
        )

    placeholder_token = secrets.token_urlsafe(32)

    if node is None:
        node = Node(
            minion_id=payload.minion_id,
            hostname=payload.minion_id.split(".")[0],
            ip_address=payload.target_ip,
            status="unknown",
            drift_score=0,
            node_token_hash=hash_password(placeholder_token),
            first_seen_at=datetime.now(UTC),
            bootstrap_status="pending",
            bootstrap_ip=payload.target_ip,
        )
        db.add(node)
        await db.flush()
        await db.commit()
        await db.refresh(node)
    # Shared queuing logic (group guard, credential persistence, audit, dispatch)
    # is also used by the bulk-import auto-bootstrap path — see bootstrap_svc.
    try:
        task = await queue_node_bootstrap(
            db,
            node,
            target_ip=payload.target_ip,
            actor=claims["email"],
            ssh_username=payload.ssh_username,
            ssh_password=payload.ssh_password,
            ssh_key=payload.ssh_key,
            salt_master_ids=payload.salt_master_ids,
            node_exporter_version=payload.node_exporter_version,
            node_exporter_listen_address=payload.node_exporter_listen_address,
            node_exporter_url_override=payload.node_exporter_url_override,
        )
    except BootstrapGroupRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return BootstrapResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        job_id=task.id,
        bootstrap_status="pending",
        message="Bootstrap queued. Node will appear in fleet once Salt minion connects.",
    )


@router.get("/bootstrap/{node_id}/status")
async def bootstrap_status(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from fleet_platform.models.bootstrap_run import BootstrapRun  # noqa: PLC0415

    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Auto-heal: if node is stuck in 'bootstrapping' but all bootstrap runs
    # for it have terminal status, reset to 'failed' so the UI doesn't hang.
    if node.bootstrap_status == "bootstrapping":
        stale_cutoff = datetime.now(UTC) - timedelta(minutes=15)
        runs = await db.execute(
            select(BootstrapRun)
            .where(BootstrapRun.node_id == node_id)
            .order_by(BootstrapRun.started_at.desc())
            .limit(1)
        )
        latest_run = runs.scalar_one_or_none()
        is_stale = (
            latest_run is None
            or latest_run.status in ("completed", "failed")
            or (latest_run.finished_at is None and latest_run.started_at < stale_cutoff)
        )
        if is_stale:
            node.bootstrap_status = "failed"
            node.bootstrap_error = "Bootstrap timed out or state was lost — use Cancel Bootstrap to reset."
            await db.commit()

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "bootstrap_ip": node.bootstrap_ip,
        "bootstrap_error": node.bootstrap_error,
    }


@router.post("/bootstrap/{node_id}/cancel")
async def cancel_bootstrap(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Reset a stuck bootstrap job so the node can be re-bootstrapped."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.bootstrap_status not in ("bootstrapping", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Bootstrap status is '{node.bootstrap_status}' — nothing to cancel",
        )
    node.bootstrap_status = "failed"
    node.bootstrap_error = "Manually cancelled by user"
    await audit(
        db,
        actor=claims["email"],
        action="node.bootstrap.cancel",
        resource_type="node",
        resource_id=node.id,
        new_value={"minion_id": node.minion_id},
    )
    await db.commit()
    return {"node_id": str(node.id), "bootstrap_status": "failed", "message": "Bootstrap cancelled"}


@router.get("/bootstrap/{node_id}/logs")
async def bootstrap_logs(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "ansible_stdout": node.bootstrap_logs,
    }


@router.get("/bootstrap/{node_id}/history")
async def bootstrap_history(
    node_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List all bootstrap runs for a node, newest first."""
    from sqlalchemy import desc  # noqa: PLC0415

    from fleet_platform.models.bootstrap_run import BootstrapRun  # noqa: PLC0415

    result = await db.execute(
        select(BootstrapRun)
        .where(BootstrapRun.node_id == node_id)
        .order_by(desc(BootstrapRun.started_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    runs = result.scalars().all()

    total = await db.scalar(
        select(func.count()).select_from(select(BootstrapRun).where(BootstrapRun.node_id == node_id).subquery())
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "target_ip": r.target_ip,
                "status": r.status,
                "error": r.error,
                "has_stdout": bool(r.ansible_stdout),
            }
            for r in runs
        ],
        "total": total or 0,
        "page": page,
        "per_page": per_page,
    }


@router.get("/bootstrap/{node_id}/history/{run_id}")
async def bootstrap_run_detail(
    node_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return full logs for a specific bootstrap run."""
    from fleet_platform.models.bootstrap_run import BootstrapRun  # noqa: PLC0415

    result = await db.execute(
        select(BootstrapRun).where(
            BootstrapRun.id == run_id,
            BootstrapRun.node_id == node_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": str(run.id),
        "node_id": str(run.node_id),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "target_ip": run.target_ip,
        "status": run.status,
        "ansible_stdout": run.ansible_stdout,
        "error": run.error,
    }
