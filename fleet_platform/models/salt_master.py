"""SaltMaster model — first-class DB entity for salt-master decoupling epic (#523).

Designed for N masters per fleet; nodes reference one via salt_master_id FK.
Provision lifecycle columns added in #556 (master-lifecycle epic).
SSoT api_url derivation added in #562: api_url is computed from address + salt_api_port + use_tls.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
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

    # SSoT api_url fields (#562): api_url is DERIVED from these — never store free-text api_url.
    salt_api_port: Mapped[int] = mapped_column(Integer, nullable=False, default=4507)
    use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Control mode: 'salt_api' | 'cli' | etc. — not user-editable (server default)
    control_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="salt_api")

    # Salt API credentials (all optional — only used when control_mode='salt_api')
    # api_url is a DERIVED column — computed from address + salt_api_port + use_tls (#562)
    api_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    # api_eauth: not user-editable; defaults to 'pam' on create
    api_eauth: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Token delivery strategy: 'ingest' | 'direct' — not user-editable (server default)
    token_delivery: Mapped[str] = mapped_column(String(50), nullable=False, default="ingest")

    # TLS + key-acceptance flags (#555)
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_accept: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Health tracking
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Provision lifecycle (#556, master-lifecycle epic)
    provision_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unprovisioned")
    os_family: Mapped[str | None] = mapped_column(String(20), nullable=True)
    salt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provision_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SSH credentials for provisioning (stored encrypted; resolution falls back to
    # global bootstrap creds at provision time — #557)
    ssh_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    ssh_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted

    # Optional link to a node record (SET NULL on node deletion)
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL", name="fk_salt_masters_node_id"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_salt_masters_name"),
        Index("idx_salt_masters_enabled", "enabled"),
        Index("idx_salt_masters_is_default", "is_default"),
        # At most one default master (#579). Partial-unique so the many
        # is_default=false rows don't collide; only the single true row is unique.
        Index(
            "uq_salt_masters_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )
