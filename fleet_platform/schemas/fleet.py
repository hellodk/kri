import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


class TagResponse(BaseModel):
    key: str
    value: str
    source: str = "user"

    model_config = {"from_attributes": True}


class NodeListItem(BaseModel):
    id: uuid.UUID
    minion_id: str
    hostname: str | None = None
    ip_address: str | None = None
    os_version: str | None = None

    @field_validator("ip_address", mode="before")
    @classmethod
    def coerce_ip(cls, v: Any) -> str | None:
        return str(v) if v is not None else None
    hardware_model: str | None = None
    status: str
    drift_score: int
    cpu_usage_pct: float | None = None
    mem_usage_pct: float | None = None
    last_seen_at: datetime | None = None
    tags: list[TagResponse]
    maintenance_mode: bool = False
    xcode_version: str | None = None
    macos_version: str | None = None
    group_count: int = 0  # number of groups this node belongs to

    model_config = {"from_attributes": True}


class NodeDetailResponse(NodeListItem):
    os_build: str | None
    cpu_cores: int | None
    ram_gb: float | None
    storage_gb: float | None
    first_seen_at: datetime
    created_at: datetime
    bootstrap_status: str = "unregistered"
    bootstrap_ip: str | None = None
    bootstrap_error: str | None = None
    bootstrap_logs: str | None = None
    # SSH credential metadata (never expose raw secrets)
    ssh_username: str | None = None
    ssh_auth_mode: str = "password"
    has_ssh_password: bool = False
    has_ssh_key: bool = False
    # VNC credential metadata (never expose raw secrets)
    has_vnc_password: bool = False

    @model_validator(mode="wrap")
    @classmethod
    def compute_ssh_flags(cls, data: Any, handler: Any) -> "NodeDetailResponse":
        """Set has_ssh_password/has_ssh_key/has_vnc_password from ORM encrypted columns without exposing secrets."""
        # FastAPI re-validates the return value through the response_model. When
        # data is already a NodeDetailResponse (from our endpoint return), the flags
        # are already correct — return it as-is to avoid re-computing from missing fields.
        if isinstance(data, cls):
            return data
        if isinstance(data, dict):
            data.setdefault("has_ssh_password", bool(data.get("ssh_password_enc")))
            data.setdefault("has_ssh_key", bool(data.get("ssh_key_enc")))
            data.setdefault("has_vnc_password", bool(data.get("vnc_password_enc")))
            return handler(data)
        # ORM object: compute flags from the encrypted column presence.
        result = handler(data)
        return result.model_copy(update={
            "has_ssh_password": bool(getattr(data, "ssh_password_enc", None)),
            "has_ssh_key": bool(getattr(data, "ssh_key_enc", None)),
            "has_vnc_password": bool(getattr(data, "vnc_password_enc", None)),
        })


class NodeCreateRequest(BaseModel):
    minion_id: str
    hostname: str | None = None
    ip_address: str | None = None
    hardware_model: str | None = None
    os_version: str | None = None


class NodeUpdateRequest(BaseModel):
    hostname: str | None = None
    ip_address: str | None = None
    hardware_model: str | None = None
    os_version: str | None = None
    # SSH credential updates (plaintext in, encrypted on save)
    ssh_username: str | None = None
    ssh_password: str | None = None   # plaintext, will be encrypted on save
    ssh_auth_mode: str | None = None  # "password" | "key"
    ssh_key: str | None = None        # plaintext key content, will be encrypted
    # VNC credential update (plaintext in, encrypted on save)
    vnc_password: str | None = None   # plaintext, will be encrypted on save


class FleetOverviewResponse(BaseModel):
    total_nodes: int
    online: int
    stale: int
    offline: int
    unknown: int
    avg_drift_score: int
    nodes_clean: int
    nodes_low: int
    nodes_medium: int
    nodes_high: int
    nodes_critical: int
    last_updated: datetime
