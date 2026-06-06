"""Monitoring summary endpoint — aggregates metrics for the built-in monitoring page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from prometheus_client import generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.schemas.monitoring import MonitoringSummarySchema
from fleet_platform.services.monitoring_svc import get_monitoring_summary

router = APIRouter(prefix="/api/v1/monitoring")


@router.get("/summary", response_model=MonitoringSummarySchema)
async def monitoring_summary(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
) -> MonitoringSummarySchema:
    """Return aggregated monitoring stats: node counts, queue depths, alert events, HTTP metrics."""
    metrics_text = generate_latest().decode("utf-8")
    result = await get_monitoring_summary(db, metrics_text)
    return MonitoringSummarySchema(**result)
