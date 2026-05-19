# fleet_platform/models/ansible_job.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class AnsibleJob(Base):
    __tablename__ = "ansible_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    playbook: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str] = mapped_column(String(255), nullable=False)
    extravars: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    triggered_by: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    rc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_ansible_jobs_status", "status", "created_at"),
    )
