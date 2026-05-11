from fastapi import APIRouter
from fleet_platform.core.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.environment,
    }
