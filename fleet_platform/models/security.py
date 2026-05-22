import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class VulnerabilityFinding(Base):
    __tablename__ = "vulnerability_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scanner: Mapped[str] = mapped_column(String(30), nullable=False)   # trivy | cxone | sonarqube
    cve_id: Mapped[str] = mapped_column(String(30), nullable=False)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    package_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)   # CRITICAL|HIGH|MEDIUM|LOW|UNKNOWN
    cvss_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fixed_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_vuln_findings_node_severity", "node_id", "severity"),
        Index("idx_vuln_findings_cve", "cve_id"),
    )


class LicenseFinding(Base):
    __tablename__ = "license_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scanner: Mapped[str] = mapped_column(String(30), nullable=False)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    package_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    license_id: Mapped[str] = mapped_column(String(100), nullable=False)   # "GPL-3.0", "MIT", etc.
    risk: Mapped[str] = mapped_column(String(20), nullable=False)           # high|medium|low|allowed
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_license_findings_node", "node_id"),
        Index("idx_license_findings_risk", "node_id", "risk"),
    )
