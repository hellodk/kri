"""Monitoring aggregation service — sources data for /monitoring/summary endpoint."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_redis
from fleet_platform.models.alert import AlertEvent
from fleet_platform.models.node import Node
from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot

_log = logging.getLogger(__name__)


async def get_node_counts(db: AsyncSession) -> dict[str, int]:
    """Return count of nodes by status: online, stale, offline, unknown."""
    rows = await db.execute(select(Node.status, func.count().label("cnt")).group_by(Node.status))
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


async def get_fleet_health_aggregates(db: AsyncSession) -> dict:
    """Aggregate latest health snapshot per node (last 2h).

    Returns dict with node_count, avg_cpu_load_1m, avg_mem_used_pct, avg_disk_pct,
    thermal_ok, nodes_with_gpu, total_gpu_vram_mb.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=2)
    # Subquery to get latest collected_at per node within cutoff
    subq = (
        select(
            NodeHealthSnapshot.node_id,
            func.max(NodeHealthSnapshot.collected_at).label("latest"),
        )
        .where(NodeHealthSnapshot.collected_at >= cutoff)
        .group_by(NodeHealthSnapshot.node_id)
        .subquery()
    )

    # Join to fetch the full snapshots at the latest timestamp
    rows = await db.execute(
        select(NodeHealthSnapshot).join(
            subq,
            and_(
                NodeHealthSnapshot.node_id == subq.c.node_id,
                NodeHealthSnapshot.collected_at == subq.c.latest,
            ),
        )
    )
    snapshots = rows.scalars().all()

    if not snapshots:
        return {
            "node_count": 0,
            "avg_cpu_load_1m": None,
            "avg_mem_used_pct": None,
            "avg_disk_pct": None,
            "thermal_ok": None,
            "nodes_with_gpu": 0,
            "total_gpu_vram_mb": 0,
        }

    def avg(lst: list[float]) -> float | None:
        return round(sum(lst) / len(lst), 1) if lst else None

    # Collect numeric values, filtering out None
    cpu_vals = [float(s.cpu_load_1m) for s in snapshots if s.cpu_load_1m is not None]
    mem_vals = [float(s.mem_used_pct) for s in snapshots if s.mem_used_pct is not None]
    disk_vals = [float(s.disk_root_pct) for s in snapshots if s.disk_root_pct is not None]

    # Count nodes with acceptable thermal pressure (None, empty, "nominal", "fair")
    thermal_ok = sum(1 for s in snapshots if s.thermal_pressure in (None, "", "nominal", "fair"))

    # GPU aggregates
    gpu_nodes = [s for s in snapshots if s.gpu_name]

    return {
        "node_count": len(snapshots),
        "avg_cpu_load_1m": avg(cpu_vals),
        "avg_mem_used_pct": avg(mem_vals),
        "avg_disk_pct": avg(disk_vals),
        "thermal_ok": thermal_ok,
        "nodes_with_gpu": len(gpu_nodes),
        "total_gpu_vram_mb": sum(s.gpu_vram_mb or 0 for s in gpu_nodes),
    }


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


async def get_maintenance_heartbeat() -> dict:
    """Read the dead-man's-switch timestamp written by mark_stale_nodes.
    Returns age in seconds and a flag if the beat worker appears stuck.
    H-4 fix (SRE audit): makes a hung beat worker immediately visible in monitoring.
    """
    from fleet_platform.workers.maintenance import _MAINTENANCE_HEARTBEAT_KEY  # noqa: PLC0415

    try:
        redis_client = await get_redis()
        value = await redis_client.get(_MAINTENANCE_HEARTBEAT_KEY)
        if value is None:
            # Key expired or never set — beat worker hasn't run in > 10 min
            return {"last_run_at": None, "age_seconds": None, "beat_ok": False}
        last_run_at = value.decode() if isinstance(value, bytes) else value
        age = (datetime.now(UTC) - datetime.fromisoformat(last_run_at)).total_seconds()
        return {
            "last_run_at": last_run_at,
            "age_seconds": round(age),
            "beat_ok": age < 600,  # warn if > 10 min since last run (2x scheduled interval)
        }
    except Exception:
        return {"last_run_at": None, "age_seconds": None, "beat_ok": None}


async def get_monitoring_summary(db: AsyncSession, metrics_text: str = "") -> dict:
    """Aggregate all monitoring data into a single summary."""
    # DB queries must run sequentially — a single AsyncSession cannot serve
    # concurrent coroutines (SQLAlchemy raises InvalidRequestError if you try).
    # Only get_celery_queue_stats() is safe to overlap because it uses Redis.
    node_counts = await get_node_counts(db)
    alert_events = await get_alert_events_24h(db)
    fleet_health = await get_fleet_health_aggregates(db)
    celery_stats = await get_celery_queue_stats()
    maintenance_hb = await get_maintenance_heartbeat()
    http_stats = parse_http_request_total(metrics_text) if metrics_text else []

    return {
        "node_counts": node_counts,
        "alert_events_24h": alert_events,
        "alert_count_24h": len(alert_events),
        "celery_queues": celery_stats,
        "http_requests": http_stats[:20],  # top 20
        "fleet_health": fleet_health,
        "maintenance_heartbeat": maintenance_hb,
        "generated_at": datetime.now(UTC).isoformat(),
    }
