# fleet_platform/api/routes/search.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Node
from fleet_platform.schemas.fleet import NodeListItem

router = APIRouter(prefix="/api/v1")


@router.get("/search")
async def search(
    q: str = Query(min_length=3, description="Search term (min 3 chars)"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    pattern = f"%{q}%"
    result = await db.execute(
        select(Node)
        .options(selectinload(Node.tags))
        .where(
            or_(
                Node.hostname.ilike(pattern),
                Node.minion_id.ilike(pattern),
            )
        )
        .limit(50)
    )
    nodes = result.scalars().all()
    return {
        "query": q,
        "nodes": [NodeListItem.model_validate(n) for n in nodes],
    }
