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
    last_seen_at: datetime | None = None
    tags: list[TagResponse]

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

    @model_validator(mode="wrap")
    @classmethod
    def compute_ssh_flags(cls, data: Any, handler: Any) -> "NodeDetailResponse":
        # Resolve has_ssh_password / has_ssh_key before Pydantic validates fields.
        # data may be an ORM object (from_attributes=True) or a plain dict.
        if isinstance(data, dict):
            data.setdefault("has_ssh_password", bool(data.get("ssh_password_enc")))
            data.setdefault("has_ssh_key", bool(data.get("ssh_key_enc")))
        else:
            # ORM object — read enc fields directly; pass as-is (from_attributes handles the rest)
            # We inject into the dict representation used by from_attributes
            # by converting to dict and letting Pydantic re-validate from that.
            pass
        result = handler(data)
        # For ORM objects, has_ssh_password/has_ssh_key default to False above;
        # override them now from the ORM attributes.
        if not isinstance(data, dict):
            object.__setattr__(result, "has_ssh_password", bool(getattr(data, "ssh_password_enc", None)))
            object.__setattr__(result, "has_ssh_key", bool(getattr(data, "ssh_key_enc", None)))
        return result


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
