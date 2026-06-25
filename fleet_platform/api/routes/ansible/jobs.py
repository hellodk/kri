# fleet_platform/api/routes/ansible/jobs.py
"""Ansible job routes: /jobs/..."""

import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.schemas.playbook import AnsibleJobResponse
from fleet_platform.services.extravars import _scrub_extravars
from fleet_platform.services.log_delta import slice_from, split_running_marker

from ._router import router


@router.get("/jobs", response_model=list[AnsibleJobResponse])
async def list_ansible_jobs(
    status: str | None = Query(None, description="Filter by status: pending|running|completed|failed"),
    node_id: str | None = Query(None, description="Filter by target node UUID"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List all ansible playbook jobs, newest first."""
    q = select(AnsibleJob).order_by(AnsibleJob.created_at.desc())
    if status:
        q = q.where(AnsibleJob.status == status)
    if node_id:
        # Include both direct-node jobs AND group jobs for groups this node belongs to
        try:
            node_uuid = uuid.UUID(node_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="node_id must be a valid UUID")
        from sqlalchemy import or_

        from fleet_platform.models.group import GroupMember

        group_ids_result = await db.execute(select(GroupMember.group_id).where(GroupMember.node_id == node_uuid))
        group_ids = [str(gid) for gid in group_ids_result.scalars().all()]
        # Match: target_id == node_id (direct) OR target_id in group_ids (group run)
        conditions = [AnsibleJob.target_id == node_id]
        if group_ids:
            conditions.append(AnsibleJob.target_id.in_(group_ids))
        q = q.where(or_(*conditions))
    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return [
        AnsibleJobResponse(
            id=j.id,
            playbook=j.playbook,
            target_type=j.target_type,
            target_label=j.target_label,
            target_id=str(j.target_id) if j.target_id else None,
            extravars=_scrub_extravars(j.extravars or {}) or {},  # type: ignore[arg-type]
            status=j.status,
            triggered_by=j.triggered_by,
            started_at=j.started_at,
            completed_at=j.completed_at,
            stdout=j.stdout,
            rc=j.rc,
            timeout_seconds=j.timeout_seconds,
            created_at=j.created_at,
            celery_task_id=j.celery_task_id,
            cancelled_at=j.cancelled_at,
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=AnsibleJobResponse)
async def get_ansible_job(
    job_id: uuid.UUID,
    from_byte: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stdout_out: str | None
    total_len: int | None
    running: str | None
    if from_byte is not None:
        base, running = split_running_marker(job.stdout)
        stdout_out = slice_from(base, from_byte)
        total_len = len(base)
    else:
        stdout_out = job.stdout
        total_len = None
        running = None

    return AnsibleJobResponse(
        id=job.id,
        playbook=job.playbook,
        target_type=job.target_type,
        target_label=job.target_label,
        target_id=str(job.target_id) if job.target_id else None,
        extravars=_scrub_extravars(job.extravars or {}) or {},  # type: ignore[arg-type]
        status=job.status,
        triggered_by=job.triggered_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        stdout=stdout_out,
        rc=job.rc,
        verbosity=job.verbosity,
        timeout_seconds=job.timeout_seconds,
        created_at=job.created_at,
        celery_task_id=job.celery_task_id,
        cancelled_at=job.cancelled_at,
        stdout_total_len=total_len,
        running_task=running,
    )


@router.post("/jobs/{job_id}/cancel", status_code=200)
async def cancel_playbook_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Cancel a running or pending playbook job (#342)."""
    from fleet_platform.workers.celery_app import celery_app as _celery

    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("running", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in terminal state '{job.status}' — cannot cancel",
        )

    # Revoke the Celery task (SIGTERM to the worker process) — best-effort
    if job.celery_task_id:
        try:
            _celery.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass  # revoke is best-effort — DB update still proceeds

    now = datetime.now(UTC)
    job.status = "cancelled"
    job.completed_at = now
    job.cancelled_at = now
    existing_stdout = job.stdout or ""
    _actor = claims.get("email") or claims.get("sub", "unknown")
    job.stdout = (existing_stdout + f"\n\n[CANCELLED] Job manually cancelled by {_actor} at {now.isoformat()}").lstrip()

    await audit(
        db,
        actor=_actor,
        action="playbook_job_cancelled",
        resource_type="ansible_job",
        resource_id=job_id,
        new_value={"job_id": str(job_id), "playbook": job.playbook},
    )
    await db.commit()  # single commit covers status + audit

    return {"job_id": str(job_id), "status": "cancelled", "message": "Job cancelled successfully"}
