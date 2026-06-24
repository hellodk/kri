"""PendingAction — human approval gate for destructive node operations (#291)."""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


def _default_token() -> str:
    return secrets.token_urlsafe(32)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approval_token: Mapped[str] = mapped_column(String(64), nullable=False, default=_default_token)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Agent write-path fields (#710 → executor #711, apply-with-approval #714).
    # When an agent proposes a gated action these carry the originating session,
    # the tool name, how many targets it hits (co-sign threshold), the captured
    # dry-run output shown to the approver, and whether a second admin must co-sign.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposed_by_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dry_run_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    co_sign_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Co-sign audit trail (#714): first approver + (when co_sign_required) admin co-signer.
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    co_signed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    co_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Agent-proposed live actions that hit more than this many targets require a
    # second admin co-sign on top of the first approval (#714, #716 decision d5).
    CO_SIGN_THRESHOLD = 8

    __table_args__ = (
        Index("idx_pending_actions_token", "approval_token", unique=True),
        Index("idx_pending_actions_status", "status"),
        Index("idx_pending_actions_session_id", "session_id"),
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

    # Critical targets that must never be stopped/disabled/signalled remotely.
    # Matches the "NEVER disable" control-plane/system list. Compared case-insensitively
    # against the bare name and against common macOS launchd label suffixes
    # (e.g. com.openssh.sshd -> sshd, com.apple.mDNSResponder -> mDNSResponder).
    PROTECTED_TARGETS = frozenset(
        {
            "salt-minion",
            "salt-master",
            "sshd",
            "mdnsresponder",
            "configd",
            "powerd",
            "securityd",
            "trustd",
            "opendirectoryd",
            "syslogd",
            "networkd",
            "launchd",
            "kernel_task",
            "windowserver",
            "exo",
        }
    )

    @classmethod
    def is_destructive(cls, action_type: str) -> bool:
        return action_type in cls.DESTRUCTIVE

    @classmethod
    def is_forbidden(cls, action_type: str) -> bool:
        return action_type in cls.FORBIDDEN

    @classmethod
    def is_protected_target(cls, name: str) -> bool:
        if not name:
            return False
        n = name.strip().lower()
        # strip common launchd label prefixes -> last dotted segment
        bare = n.rsplit(".", 1)[-1] if "." in n else n
        return n in cls.PROTECTED_TARGETS or bare in cls.PROTECTED_TARGETS
