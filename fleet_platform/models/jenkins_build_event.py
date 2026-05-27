import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class JenkinsBuildEvent(Base):
    __tablename__ = "jenkins_build_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    def __init__(self, **kw: object) -> None:
        if "id" not in kw:
            kw["id"] = uuid.uuid4()
        super().__init__(**kw)

    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    build_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # SUCCESS, FAILURE, UNSTABLE, ABORTED
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    test_pass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_fail: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_name", "build_number", name="uq_jenkins_build_job_number"),
        Index("idx_jenkins_build_started_at", "started_at"),
        Index("idx_jenkins_build_result", "result"),
    )
