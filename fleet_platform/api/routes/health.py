from fastapi import APIRouter
from fleet_platform.core.config import settings, VERSION

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "version": VERSION,
        "environment": settings.environment,
    }
