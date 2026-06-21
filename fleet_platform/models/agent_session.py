"""AgentSession — one bounded agent run (planner → tools → result) (#710).

Groups the LLM queries and tool dispatches of a single agent turn so a multi-tool,
multi-iteration run can be represented, audited and rate-limited as a unit. Every
session is owned by an operator (``user_id``) — the agent never acts as "agent";
that email is the confused-deputy answer to "who fired this?" (#714).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_endpoints.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    initial_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_agent_sessions_user_id", "user_id", "created_at"),
        Index("idx_agent_sessions_status", "status"),
    )

    # Lifecycle states. `active` while the loop runs; terminal states are set when
    # the loop ends, hits a bound, or the 90-day retention sweeper expires it (#715).
    STATUSES = frozenset({"active", "completed", "aborted", "expired"})

    @classmethod
    def is_valid_status(cls, status: str) -> bool:
        return status in cls.STATUSES
