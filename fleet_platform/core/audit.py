# fleet_platform/core/audit.py
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.audit import AuditEvent


async def audit(
    db: AsyncSession,
    actor: str,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    new_value: dict | None = None,
    old_value: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Write an audit event. Must be called before db.commit() to share the transaction."""
    db.add(AuditEvent(
        event_at=datetime.now(UTC),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        new_value=new_value,
        old_value=old_value,
        ip_address=ip_address,
    ))
