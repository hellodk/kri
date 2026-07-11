# fleet_platform/models/fleet_recommendation.py
"""Fleet-wide, LLM-generated recommendations, stored for daily + on-demand display (#4)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class FleetRecommendation(Base):
    """A single generated batch of fleet-wide AI recommendations.

    Replaces the per-node "Ask AI" quick-fix (#294) with a fleet-wide,
    scheduled + on-demand recommendation feed (#4). Only the latest row is
    normally surfaced to the UI; history is retained for audit/trend.
    """

    __tablename__ = "fleet_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("idx_fleet_recommendations_generated_at", "generated_at"),)
