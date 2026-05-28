"""Monitoring aggregation service — sources data for /monitoring/summary endpoint."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_redis
from fleet_platform.models.alert import AlertEvent
from fleet_platform.models.node import Node

_log = logging.getLogger(__name__)


async def get_node_counts(db: AsyncSession) -> dict[str, int]:
    """Return count of nodes by status: online, stale, offline, unknown."""
    rows = await db.execute(
        select(Node.status, func.count().label("cnt")).group_by(Node.status)
    )
    counts: dict[str, int] = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
    for status, cnt in rows.all():
        if status in counts:
            counts[status] += cnt
        else:
            counts["unknown"] += cnt
    counts["total"] = sum(counts.values())
    return counts


async def get_alert_events_24h(db: AsyncSession) -> list[dict]:
    """Return alert events fired in the last 24 hours."""
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    rows = await db.execute(
        select(AlertEvent.id, AlertEvent.message, AlertEvent.fired_at)
        .where(AlertEvent.fired_at >= cutoff)
        .order_by(AlertEvent.fired_at.desc())
        .limit(50)
    )
    return [
        {
            "id": str(r.id),
            "message": r.message,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
        }
        for r in rows.all()
    ]


async def get_celery_queue_stats() -> dict[str, int]:
    """Return queue depth per queue from Redis.

    Celery tasks are stored as Redis list elements. Each queue has a key of the same name.
    Returns counts for: default, maintenance, drift, sbom queues plus active task count.
    """
    queues = ["default", "maintenance", "drift", "sbom"]
    stats: dict[str, int] = {}
    active_count = 0
    try:
        redis_client = await get_redis()
        for q in queues:
            length = redis_client.llen(q)
            stats[q] = int(await length)  # type: ignore[misc]
        # Active tasks: try Celery inspect with short timeout
        from fleet_platform.workers.celery_app import celery_app  # noqa: PLC0415
        inspector = celery_app.control.inspect(timeout=1)
        try:
            active = await asyncio.get_event_loop().run_in_executor(None, inspector.active)
            if active:
                active_count = sum(len(tasks) for tasks in active.values())
        except Exception:
            active_count = 0
    except Exception as exc:
        _log.warning("get_celery_queue_stats: Redis unavailable, returning zeros: %s", exc)
        for q in queues:
            stats[q] = 0
    stats["active"] = active_count
    return stats


def parse_http_request_total(metrics_text: str) -> list[dict]:
    """Parse http_requests_total counter from Prometheus text format.

    Returns list of {handler, method, status_code, count}.
    """
    results = []
    pattern = re.compile(r"http_requests_total\{([^}]+)\}\s+([\d.e+]+)")
    for match in pattern.finditer(metrics_text):
        labels_str = match.group(1)
        count_str = match.group(2)
        labels: dict[str, str] = {}
        for part in labels_str.split(","):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
        results.append(
            {
                "handler": labels.get("handler", "unknown"),
                "method": labels.get("method", "unknown"),
                "status_code": labels.get("status_code", "unknown"),
                "count": int(float(count_str)),
            }
        )
    return results


async def get_monitoring_summary(db: AsyncSession, metrics_text: str = "") -> dict:
    """Aggregate all monitoring data into a single summary."""
    node_counts = await get_node_counts(db)
    alert_events = await get_alert_events_24h(db)
    celery_stats = await get_celery_queue_stats()
    http_stats = parse_http_request_total(metrics_text) if metrics_text else []

    return {
        "node_counts": node_counts,
        "alert_events_24h": alert_events,
        "alert_count_24h": len(alert_events),
        "celery_queues": celery_stats,
        "http_requests": http_stats[:20],  # top 20
        "generated_at": datetime.now(UTC).isoformat(),
    }
