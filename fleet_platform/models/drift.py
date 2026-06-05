import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base, TimestampMixin


class DesiredStateBaseline(Base, TimestampMixin):
    __tablename__ = "desired_state_baselines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    git_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    state_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DriftRecord(Base):
    """TimescaleDB hypertable — partition key: computed_at"""

    __tablename__ = "drift_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("desired_state_baselines.id", ondelete="SET NULL"),
        nullable=True,
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    drift_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    missing_packages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extra_packages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    version_mismatches: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    service_drift: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    config_drift: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("idx_drift_records_node_id", "node_id", "computed_at"),
        Index("idx_drift_records_score", "drift_score", "computed_at"),
    )
