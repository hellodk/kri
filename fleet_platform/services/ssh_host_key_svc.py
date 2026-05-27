"""TOFU (Trust-On-First-Use) SSH host key management."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.node import Node

logger = logging.getLogger(__name__)


async def verify_or_store_host_key(
    node: Node,
    host_key_b64: str,
    db: AsyncSession,
    user_id: str | None = None,
) -> bool:
    """TOFU check for SSH host key.

    - First connection: stores the key, returns True.
    - Subsequent connections: returns True if key matches stored.
    - Mismatch: logs a security event, returns False (caller must abort).
    """
    if not node.ssh_host_key:
        node.ssh_host_key = host_key_b64
        await db.commit()
        logger.info("TOFU: stored host key for node %s (%s)", node.id, node.hostname)
        return True

    if node.ssh_host_key == host_key_b64:
        return True

    logger.warning(
        "SSH host key mismatch for node %s (%s) — possible MitM attack",
        node.id,
        node.hostname,
    )
    # Import SecurityEvent here to avoid circular imports
    from fleet_platform.models.ssh_session import SecurityEvent  # noqa: PLC0415

    user_uuid: uuid.UUID | None = None
    if user_id is not None:
        try:
            user_uuid = uuid.UUID(user_id)
        except (ValueError, AttributeError):
            user_uuid = None

    event = SecurityEvent(
        node_id=node.id,
        user_id=user_uuid,
        event_type="ssh_host_key_mismatch",
        severity="critical",
        detail=(
            f"Expected key: {node.ssh_host_key[:40]}... "
            f"Got key: {host_key_b64[:40]}..."
        ),
        created_at=datetime.now(UTC),
    )
    db.add(event)
    await db.commit()
    return False
