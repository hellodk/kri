# fleet_platform/api/routes/fleet.py
import json
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Node
from fleet_platform.schemas.fleet import FleetOverviewResponse

router = APIRouter(prefix="/api/v1/fleet")

_OVERVIEW_CACHE_KEY = "fleet:overview"
_OVERVIEW_TTL = 15  # seconds


@router.get("/overview", response_model=FleetOverviewResponse)
async def fleet_overview(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    cached = await redis.get(_OVERVIEW_CACHE_KEY)
    if cached:
        return FleetOverviewResponse(**json.loads(cached))

    rows = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((Node.status == "online", 1), else_=0)).label("online"),
            func.sum(case((Node.status == "stale", 1), else_=0)).label("stale"),
            func.sum(case((Node.status == "offline", 1), else_=0)).label("offline"),
            func.sum(case((Node.status == "unknown", 1), else_=0)).label("unknown"),
            func.coalesce(func.avg(Node.drift_score), 0).label("avg_drift"),
            func.sum(case((Node.drift_score <= 5, 1), else_=0)).label("clean"),
            func.sum(case(((Node.drift_score >= 6) & (Node.drift_score <= 20), 1), else_=0)).label("low"),
            func.sum(case(((Node.drift_score >= 21) & (Node.drift_score <= 50), 1), else_=0)).label("medium"),
            func.sum(case(((Node.drift_score >= 51) & (Node.drift_score <= 80), 1), else_=0)).label("high"),
            func.sum(case((Node.drift_score >= 81, 1), else_=0)).label("critical"),
        )
    )
    row = rows.one()
    now = datetime.now(UTC)

    data = FleetOverviewResponse(
        total_nodes=row.total or 0,
        online=row.online or 0,
        stale=row.stale or 0,
        offline=row.offline or 0,
        unknown=row.unknown or 0,
        avg_drift_score=int(row.avg_drift or 0),
        nodes_clean=row.clean or 0,
        nodes_low=row.low or 0,
        nodes_medium=row.medium or 0,
        nodes_high=row.high or 0,
        nodes_critical=row.critical or 0,
        last_updated=now,
    )

    await redis.setex(_OVERVIEW_CACHE_KEY, _OVERVIEW_TTL, data.model_dump_json())
    return data
