# fleet_platform/core/audit.py
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.audit import AuditEvent

_SENSITIVE = re.compile(r'password|secret|token|api_key|apikey|passphrase', re.I)
_REDACTED = '[redacted]'


def _scrub(d: dict | None) -> dict | None:
    """Replace values of sensitive keys with [redacted] before persisting."""
    if not d:
        return d
    return {k: _REDACTED if _SENSITIVE.search(k) else v for k, v in d.items()}


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
    """Write an audit event. Must be called before db.commit() to share the transaction.
    Sensitive keys (password, secret, token, api_key, passphrase) are redacted.
    """
    db.add(AuditEvent(
        event_at=datetime.now(UTC),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        new_value=_scrub(new_value),
        old_value=_scrub(old_value),
        ip_address=ip_address,
    ))
