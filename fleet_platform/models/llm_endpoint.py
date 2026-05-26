import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class LLMEndpoint(Base):
    __tablename__ = "llm_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, insert_sentinel=False
    )

    def __init__(self, **kw: object) -> None:
        if "id" not in kw:
            kw["id"] = uuid.uuid4()
        super().__init__(**kw)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # "openai_compat" covers OpenAI, Ollama, LM Studio, vLLM, Groq, Mistral
    # "anthropic" uses the native Anthropic SDK
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Fernet-encrypted ciphertext; None for keyless providers (e.g. local Ollama)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_llm_endpoints_is_default", "is_default"),
        Index("idx_llm_endpoints_enabled", "enabled"),
    )

    @property
    def has_api_key(self) -> bool:
        return self.api_key_encrypted is not None
