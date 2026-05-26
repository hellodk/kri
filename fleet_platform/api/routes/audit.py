# fleet_platform/api/routes/audit.py
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.audit import AuditEvent
from fleet_platform.schemas.common import PaginatedResponse

router = APIRouter(prefix="/api/v1/audit")


class AuditEventResponse(BaseModel):
    id: int
    event_at: datetime
    actor: str
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    ip_address: str | None

    model_config = {"from_attributes": True}

    @classmethod
    def _from_orm(cls, obj):
        """Build response from ORM object, coercing INET → str."""
        ip = obj.ip_address
        return cls(
            id=obj.id,
            event_at=obj.event_at,
            actor=obj.actor,
            action=obj.action,
            resource_type=obj.resource_type,
            resource_id=obj.resource_id,
            ip_address=str(ip) if ip is not None else None,
        )


@router.get("", response_model=PaginatedResponse[AuditEventResponse])
async def list_audit_logs(
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(AuditEvent)

    if actor:
        query = query.where(AuditEvent.actor.ilike(f"%{actor}%"))
    if action:
        query = query.where(AuditEvent.action.ilike(f"%{action}%"))
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = query.order_by(AuditEvent.event_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    events = result.scalars().all()

    return PaginatedResponse(
        items=[AuditEventResponse._from_orm(e) for e in events],
        total=total,
        page=page,
        per_page=per_page,
    )
