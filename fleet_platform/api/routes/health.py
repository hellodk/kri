from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.config import VERSION, settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "environment": settings.environment}


@router.get("/health/ready")
async def health_ready(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    checks: dict[str, str] = {}
    overall = "ready"

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        overall = "degraded"

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
        overall = "degraded"

    http_status = 200 if overall == "ready" else 503
    return JSONResponse(
        status_code=http_status,
        content={"status": overall, "version": VERSION, "checks": checks},
    )
