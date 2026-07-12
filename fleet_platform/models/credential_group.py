"""Credential <-> Group association (#983 — normalized credential model, Phase 1).

Replaces the embedded ``Group.credential_id`` / ``Node.credential_id`` FKs with a
single association table: one credential per group (``UNIQUE(group_id)``), a
credential may cover many groups. Resolution is now strictly
``node -> group_members -> groups -> credential_groups -> credential`` — see
``fleet_platform.services.credential_resolver``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class CredentialGroup(Base):
    __tablename__ = "credential_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("group_id", name="uq_credential_groups_group_id"),
        Index("idx_credential_groups_credential_id", "credential_id"),
    )
