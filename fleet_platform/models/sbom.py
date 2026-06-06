import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class SBOMScan(Base):
    __tablename__ = "sbom_scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    syft_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="cyclonedx")
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    component_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SBOMComponent(Base):
    __tablename__ = "sbom_components"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sbom_scans.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purl: Mapped[str | None] = mapped_column(String(500), nullable=True)
    component_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    licenses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cpes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # search_vector is a GENERATED column added via raw SQL in the Alembic migration

    __table_args__ = (
        Index("idx_sbom_components_node_id", "node_id"),
        Index("idx_sbom_components_name", "name"),
        Index("idx_sbom_components_purl", "purl"),
    )
