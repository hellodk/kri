import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VALID_PROVIDERS = Literal["openai_compat", "anthropic", "ollama", "vllm", "llamacpp"]
VALID_INTENTS = Literal["salt_state", "ansible_playbook", "fleet_command", "explain"]


class LLMEndpointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: VALID_PROVIDERS
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str | None = None
    model: str = Field(..., min_length=1, max_length=255)
    max_tokens: int = Field(default=4096, ge=256, le=128000)
    is_default: bool = False
    enabled: bool = True


class LLMEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: VALID_PROVIDERS | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    max_tokens: int | None = Field(default=None, ge=256, le=128000)
    is_default: bool | None = None
    enabled: bool | None = None


class LLMEndpointResponse(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    has_api_key: bool
    model: str
    max_tokens: int
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LLMEndpointTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


class LLMQueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    intent: VALID_INTENTS
    endpoint_id: uuid.UUID | None = None


class LLMQueryResponse(BaseModel):
    query_id: uuid.UUID
    intent: str
    result: str
    model_used: str
    endpoint_name: str
    input_tokens: int
    output_tokens: int
    duration_ms: int


class LLMQueryLogEntry(BaseModel):
    id: uuid.UUID
    intent: str
    prompt: str
    model_used: str | None
    duration_ms: int | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
