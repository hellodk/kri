"""Monitoring API response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class NodeCountsSchema(BaseModel):
    online: int
    stale: int
    offline: int
    unknown: int
    total: int


class AlertEventSchema(BaseModel):
    id: str
    message: str
    fired_at: str | None


class CeleryQueuesSchema(BaseModel):
    default: int
    maintenance: int
    drift: int
    sbom: int
    active: int


class HttpRequestSchema(BaseModel):
    handler: str
    method: str
    status_code: str
    count: int


class FleetHealthSchema(BaseModel):
    node_count: int
    avg_cpu_load_1m: float | None
    avg_mem_used_pct: float | None
    avg_disk_pct: float | None
    thermal_ok: int | None
    nodes_with_gpu: int
    total_gpu_vram_mb: int


class MaintenanceHeartbeatSchema(BaseModel):
    last_run_at: str | None
    age_seconds: int | None
    beat_ok: bool | None   # None = Redis unavailable


class MonitoringSummarySchema(BaseModel):
    node_counts: NodeCountsSchema
    alert_events_24h: list[AlertEventSchema]
    alert_count_24h: int
    celery_queues: CeleryQueuesSchema
    http_requests: list[HttpRequestSchema]
    fleet_health: FleetHealthSchema
    maintenance_heartbeat: MaintenanceHeartbeatSchema
    generated_at: str
