import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VALID_PROVIDERS = Literal["openai_compat", "anthropic", "ollama", "vllm", "llamacpp"]
VALID_INTENTS = Literal["salt_state", "ansible_playbook", "fleet_command", "explain", "fleet_query", "auto"]

# How the agent loop exposes tools to an endpoint (#710):
#   native    — provider-native tool-calling (OpenAI tools=[...])
#   anthropic — Anthropic tool_use blocks
#   json      — tool schema embedded in the prompt, JSON reply parsed out
#   none      — no tools exposed (plain chat / read-only Q&A)
VALID_TOOL_MODES = ("native", "json", "anthropic", "none")
ToolMode = Literal["native", "json", "anthropic", "none"]


def normalize_tool_mode(value: str | None) -> str:
    """Resolve a stored/legacy tool_mode to a safe value for the call path.

    Unknown or NULL values fall back to ``json`` (prompt-embedded), which works
    on every backend, so a legacy DB row never breaks a call.
    """
    return value if value in VALID_TOOL_MODES else "json"


class DiscoveredModel(BaseModel):
    id: str
    name: str
    healthy: bool
    latency_ms: int | None = None


class LLMEndpointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: VALID_PROVIDERS
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str | None = None
    model: str = Field(..., min_length=1, max_length=255)
    max_tokens: int = Field(default=4096, ge=256, le=200000)
    is_default: bool = False
    enabled: bool = True
    model_context_length: int | None = None
    model_capabilities: list[str] | None = None
    tool_mode: ToolMode = "json"


class LLMEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: VALID_PROVIDERS | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    max_tokens: int | None = Field(default=None, ge=256, le=200000)
    is_default: bool | None = None
    enabled: bool | None = None
    model_context_length: int | None = None
    model_capabilities: list[str] | None = None
    tool_mode: ToolMode | None = None


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
    model_context_length: int | None = None
    model_capabilities: list[str] | None = None
    tool_mode: str = "json"

    model_config = {"from_attributes": True}


class LLMEndpointTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class LLMQueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    intent: VALID_INTENTS
    endpoint_id: uuid.UUID | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=50)


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
