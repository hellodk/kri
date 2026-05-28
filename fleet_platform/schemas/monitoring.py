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


class MonitoringSummarySchema(BaseModel):
    node_counts: NodeCountsSchema
    alert_events_24h: list[AlertEventSchema]
    alert_count_24h: int
    celery_queues: CeleryQueuesSchema
    http_requests: list[HttpRequestSchema]
    generated_at: str
