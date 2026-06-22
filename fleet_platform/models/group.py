import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base, TimestampMixin


class Group(Base, TimestampMixin):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    predicate: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # SSH credentials (inherited by all group member nodes unless overridden at node level).
    # DEPRECATED (#704/#697): superseded by ``credential_id`` -> ``credentials``.
    # Retained one release as a read-fallback; dropped in a follow-up migration.
    ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_auth_mode: Mapped[str] = mapped_column(String(10), default="password")
    ssh_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_max_mins: Mapped[int] = mapped_column(Integer, default=60)
    session_retention_days: Mapped[int] = mapped_column(Integer, default=30)

    # First-class Credential store reference (#703).
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Tiebreak when a node belongs to 2+ credential-bearing groups (#699).
    # Higher wins; alphabetical name remains the stable final tiebreak.
    credential_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("idx_group_members_node_id", "node_id"),)
