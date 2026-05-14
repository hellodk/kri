# fleet_platform/api/routes/executions.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.execution import ExecutionJobResponse, ExecutionResultResponse

router = APIRouter(prefix="/api/v1/executions")


@router.get("", response_model=PaginatedResponse[ExecutionJobResponse])
async def list_executions(
    status: str | None = None,
    node_id: uuid.UUID | None = None,
    page: int = 1,
    per_page: int = 25,
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

    return PaginatedResponse(
        items=[ExecutionJobResponse.model_validate(j) for j in jobs],
        total=total, page=page, per_page=per_page,
    )


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
    return ExecutionJobResponse.model_validate(job)


@router.get("/{job_id}/results", response_model=PaginatedResponse[ExecutionResultResponse])
async def get_execution_results(
    job_id: uuid.UUID,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(
        select(func.count()).where(ExecutionResult.job_id == job_id)
    )).scalar_one()

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
        total=total, page=page, per_page=per_page,
    )
