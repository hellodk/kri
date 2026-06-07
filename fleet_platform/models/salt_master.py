"""SaltMaster model — first-class DB entity for salt-master decoupling epic (#523).

Designed for N masters per fleet; nodes reference one via salt_master_id FK.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base, TimestampMixin


class SaltMaster(Base, TimestampMixin):
    __tablename__ = "salt_masters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Connection
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    publish_port: Mapped[int] = mapped_column(Integer, nullable=False, default=4505)
    ret_port: Mapped[int] = mapped_column(Integer, nullable=False, default=4506)

    # Control mode: 'salt_api' | 'cli' | etc.
    control_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="salt_api")

    # Salt API credentials (all optional — only used when control_mode='salt_api')
    api_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    api_eauth: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Token delivery strategy: 'ingest' | 'direct'
    token_delivery: Mapped[str] = mapped_column(String(50), nullable=False, default="ingest")

    # TLS + key-acceptance flags (#555)
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_accept: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Health tracking
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("name", name="uq_salt_masters_name"),
        Index("idx_salt_masters_enabled", "enabled"),
        Index("idx_salt_masters_is_default", "is_default"),
    )
