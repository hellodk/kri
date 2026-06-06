"""SQLAlchemy model for the fleet_embeddings pgvector table.

Used by the RAG knowledge-plane pipeline (closes #263).
source_type: node | playbook | salt_state | drift | event | doc
source_id:   stable identifier (file path, node UUID, drift record id)
content_hash: sha256 of chunk_text — skip re-embedding if unchanged
"""

import uuid
from datetime import datetime

from sqlalchemy import Computed, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base

# pgvector type — imported lazily to avoid hard dep at import time
try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import]

    _VECTOR_TYPE = Vector(768)
except ImportError:
    from sqlalchemy import Text as _VectorFallback  # noqa: F401 — dev only

    _VECTOR_TYPE = Text()  # type: ignore[assignment]


class FleetEmbedding(Base):
    """One embedded chunk of fleet knowledge."""

    __tablename__ = "fleet_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(_VECTOR_TYPE, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tsv: Mapped[None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', chunk_text)", persisted=True),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_fleet_embeddings_source", "source_type", "source_id"),
        Index("idx_fleet_embeddings_hash", "content_hash"),
    )
