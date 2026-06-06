# fleet_platform/api/routes/executions.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.models.group import Group
from fleet_platform.models.node import Node
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.execution import ExecutionJobResponse, ExecutionResultResponse

router = APIRouter(prefix="/api/v1/executions")


async def _resolve_label(db: AsyncSession, target_type: str, target_id: uuid.UUID | None) -> str | None:
    """Resolve a target UUID to a human-readable label (hostname or group name)."""
    if not target_id:
        return None
    if target_type == "node":
        row = await db.execute(select(Node.hostname, Node.minion_id).where(Node.id == target_id))
        n = row.one_or_none()
        return (n.hostname or n.minion_id) if n else str(target_id)[:8]
    if target_type == "group":
        row = await db.execute(select(Group.name).where(Group.id == target_id))
        g = row.scalar_one_or_none()
        return g if g else str(target_id)[:8]
    return None


def _to_response(job: ExecutionJob, label: str | None) -> ExecutionJobResponse:
    r = ExecutionJobResponse.model_validate(job)
    r.target_label = label
    return r


@router.get("", response_model=PaginatedResponse[ExecutionJobResponse])
async def list_executions(
    status: str | None = None,
    node_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(ExecutionJob).order_by(ExecutionJob.started_at.desc())

    if status:
        query = query.where(ExecutionJob.status == status)
    if node_id:
        query = query.where(ExecutionJob.target_id == node_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    jobs = result.scalars().all()

    items = []
    for j in jobs:
        label = await _resolve_label(db, j.target_type, j.target_id)
        items.append(_to_response(j, label))

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{job_id}", response_model=ExecutionJobResponse)
async def get_execution(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(select(ExecutionJob).where(ExecutionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    label = await _resolve_label(db, job.target_type, job.target_id)
    return _to_response(job, label)


@router.get("/{job_id}/results", response_model=PaginatedResponse[ExecutionResultResponse])
async def get_execution_results(
    job_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).where(ExecutionResult.job_id == job_id))).scalar_one()

    result = await db.execute(
        select(ExecutionResult)
        .where(ExecutionResult.job_id == job_id)
        .order_by(ExecutionResult.completed_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    results = result.scalars().all()

    return PaginatedResponse(
        items=[ExecutionResultResponse.model_validate(r) for r in results],
        total=total,
        page=page,
        per_page=per_page,
    )
