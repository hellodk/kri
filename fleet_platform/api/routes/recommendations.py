# fleet_platform/api/routes/recommendations.py
"""Fleet-wide AI recommendations (#4): stored, scheduled + on-demand.

Replaces the per-node "Ask AI" quick-fix (#294) with a single fleet-wide
recommendation feed, generated daily via Celery beat and refreshable on
demand by an operator.
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import require_role
from fleet_platform.services.fleet_recommendations_svc import (
    generate_fleet_recommendations,
    get_latest_recommendation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


class FleetRecommendationResponse(BaseModel):
    id: uuid.UUID
    generated_at: datetime
    content: str
    model: str
    provider: str | None
    node_count: int
    generated_by: str | None

    model_config = {"from_attributes": True}


@router.get("")
async def get_recommendations(
    response: Response,
    db: AsyncSession = Depends(get_db),
    _claims: dict = Depends(require_role("operator", "admin")),
) -> FleetRecommendationResponse | None:
    """Return the latest stored fleet recommendation, or 204 if none exist yet."""
    latest = await get_latest_recommendation(db)
    if latest is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return FleetRecommendationResponse.model_validate(latest)


@router.post("/generate", response_model=FleetRecommendationResponse)
@limiter.limit("2/minute")
async def generate_recommendations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Generate a fresh fleet-wide recommendation set on demand."""
    from fleet_platform.services.llm_caller import LLMCallError

    try:
        recommendation = await generate_fleet_recommendations(db, generated_by=claims.get("email", "unknown"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMCallError as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc
    return FleetRecommendationResponse.model_validate(recommendation)
