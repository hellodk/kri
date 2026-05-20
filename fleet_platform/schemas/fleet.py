import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


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
