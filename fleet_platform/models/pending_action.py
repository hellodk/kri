"""PendingAction — human approval gate for destructive node operations (#291)."""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


def _default_token() -> str:
    return secrets.token_urlsafe(32)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approval_token: Mapped[str] = mapped_column(String(64), nullable=False, default=_default_token)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_pending_actions_token", "approval_token", unique=True),
        Index("idx_pending_actions_status", "status"),
    )

    # Destructive actions that require email approval
    DESTRUCTIVE = frozenset(
        {
            "process_stop",  # SIGTERM
            "process_suspend",  # SIGSTOP
            "service_stop",
            "service_disable",
        }
    )

    # Blocked entirely
    FORBIDDEN = frozenset({"process_kill"})  # SIGKILL — never allowed remotely

    @classmethod
    def is_destructive(cls, action_type: str) -> bool:
        return action_type in cls.DESTRUCTIVE

    @classmethod
    def is_forbidden(cls, action_type: str) -> bool:
        return action_type in cls.FORBIDDEN
