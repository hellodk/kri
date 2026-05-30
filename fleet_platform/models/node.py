import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fleet_platform.models.base import Base, TimestampMixin


class Node(Base, TimestampMixin):
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    minion_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os_build: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hardware_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cpu_cores: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    ram_gb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    storage_gb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    drift_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    node_token_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bootstrap_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unregistered"
    )
    bootstrap_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    bootstrap_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    bootstrap_logs: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Per-node SSH credentials (encrypted at rest)
    ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_auth_mode: Mapped[str] = mapped_column(String(10), default="password")  # "password" | "key"
    ssh_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Per-node VNC password (encrypted at rest)
    vnc_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    maintenance_mode: Mapped[bool] = mapped_column(default=False, nullable=False)

    # SSH host key (TOFU — Trust-On-First-Use, stored on first connection)
    ssh_host_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # iOS-specific tracking fields (added by migration 017)
    xcode_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    macos_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="node", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_nodes_status", "status"),
        Index("idx_nodes_drift_score", "drift_score"),
        Index("idx_nodes_last_seen", "last_seen_at"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    node: Mapped["Node"] = relationship("Node", back_populates="tags")

    __table_args__ = (
        UniqueConstraint("node_id", "key", name="uq_tags_node_key"),
        Index("idx_tags_key_value", "key", "value"),
        Index("idx_tags_source", "source"),
    )
