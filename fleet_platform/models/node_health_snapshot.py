# fleet_platform/models/node_health_snapshot.py
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class NodeHealthSnapshot(Base):
    __tablename__ = "node_health_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    def __init__(self, **kw: object) -> None:
        if "id" not in kw:
            kw["id"] = uuid.uuid4()
        super().__init__(**kw)

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    minion_id: Mapped[str] = mapped_column(String(255), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Disk
    disk_root_used_gb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    disk_root_total_gb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    disk_root_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    disk_root_inodes_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Memory
    mem_total_gb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    mem_available_gb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    mem_used_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # CPU
    cpu_load_1m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    cpu_load_5m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    cpu_load_15m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # System
    uptime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # GPU
    gpu_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gpu_vram_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Power & thermal (powermetrics — requires sudo on minion)
    cpu_power_mw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_power_mw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thermal_pressure: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Collection error (set when any command fails)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_node_health_node_collected", "node_id", "collected_at"),
    )
