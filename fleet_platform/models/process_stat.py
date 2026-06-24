# fleet_platform/models/process_stat.py
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class NodeProcessStat(Base):
    __tablename__ = "node_process_stats"

    # Composite PK — TimescaleDB requires the partition column (collected_at) in the PK.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        server_default=func.now(),
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
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cmdline: Mapped[str | None] = mapped_column(Text, nullable=True)
    cpu_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    mem_rss_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    num_threads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    io_read_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    io_write_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_llm: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )

    __table_args__ = (
        Index("idx_node_process_node_collected", "node_id", "collected_at"),
        UniqueConstraint(
            "node_id",
            "collected_at",
            "pid",
            name="uq_node_process_stat_node_ts_pid",
        ),
    )
