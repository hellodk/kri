# fleet_platform/models/node_process_stat.py
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class NodeProcessStat(Base):
    """Per-process resource sample collected from a fleet node (psutil agent).

    Stored as a TimescaleDB hypertable on ``collected_at`` (see migration 047).
    TimescaleDB requires the partition column in every unique constraint, so the
    primary key is composite: ``(id, collected_at)``.
    """

    __tablename__ = "node_process_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False, server_default=func.now()
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

    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cmdline: Mapped[str | None] = mapped_column(Text, nullable=True)

    cpu_pct: Mapped[float] = mapped_column(Float, nullable=False)
    mem_rss_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mem_pct: Mapped[float] = mapped_column(Float, nullable=False)
    num_threads: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)

    io_read_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    io_write_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    is_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)

    __table_args__ = (Index("idx_node_process_node_collected", "node_id", "collected_at"),)
