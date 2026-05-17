# fleet_platform/api/routes/baselines.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.drift import DesiredStateBaseline
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.drift import BaselineCreate, BaselineResponse

router = APIRouter(prefix="/api/v1/baselines")


@router.get("", response_model=PaginatedResponse[BaselineResponse])
async def list_baselines(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(DesiredStateBaseline))).scalar_one()
    result = await db.execute(
        select(DesiredStateBaseline)
        .order_by(DesiredStateBaseline.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    baselines = result.scalars().all()
    return PaginatedResponse(
        items=[BaselineResponse.model_validate(b) for b in baselines],
        total=total, page=page, per_page=per_page,
    )


@router.post("", response_model=BaselineResponse, status_code=201)
async def create_baseline(
    payload: BaselineCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    baseline = DesiredStateBaseline(
        name=payload.name,
        description=payload.description,
        target_type=payload.target_type,
        target_id=payload.target_id,
        git_commit_sha=payload.git_commit_sha,
        state_json=payload.state_json,
    )
    db.add(baseline)
    await db.commit()
    await db.refresh(baseline)
    return BaselineResponse.model_validate(baseline)


@router.get("/{baseline_id}", response_model=BaselineResponse)
async def get_baseline(
    baseline_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(DesiredStateBaseline).where(DesiredStateBaseline.id == baseline_id)
    )
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
    return BaselineResponse.model_validate(baseline)
