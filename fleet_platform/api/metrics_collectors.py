# fleet_platform/api/metrics_collectors.py
"""Custom Prometheus metric collectors that bridge the worker-to-API gap.

The Celery worker writes SSH probe results to a Redis hash.  This module
reads those results on every /metrics scrape and refreshes the
``kri_node_ssh_reachable`` Gauge labels so that Prometheus sees current
per-node reachability values without any cross-process registry sharing.

Also refreshes fleet node-count gauges (kri_nodes_total/online/offline) from
the DB on each scrape (#576), and exports the Celery beat dead-man heartbeat
as ``kri_beat_last_run_timestamp_seconds`` so Alertmanager can fire when beat
is silent.

Design constraints (issue #356 / #576):
- /metrics must never return HTTP 500.  All Redis/DB errors are swallowed and
  logged at DEBUG level; the Gauge simply retains its last-known values.
- The Redis read uses a short socket timeout (1 s) to avoid blocking the
  scrape for a meaningful period if Redis is slow.
"""

from __future__ import annotations

import logging

from fleet_platform.metrics import (
    beat_last_run_timestamp_seconds,
    embedding_index_staleness_seconds,
    node_ssh_reachable,
    nodes_offline,
    nodes_online,
    nodes_total,
    pending_action_queue_depth,
)

logger = logging.getLogger(__name__)

_SSH_REDIS_HASH = "kri:ssh_reachable"
_MAINTENANCE_HEARTBEAT_KEY = "kri:maintenance:last_run"


def refresh_ssh_reachability_gauge() -> None:
    """Read ``kri:ssh_reachable`` from Redis and update the ``kri_node_ssh_reachable`` Gauge.

    Called by the /metrics endpoint handler in :mod:`fleet_platform.api.main`
    immediately before :func:`prometheus_client.generate_latest` so that each
    scrape reflects the most recent worker run.

    Errors are silently swallowed — the scrape endpoint must remain available
    even when Redis is down.
    """
    try:
        # Import lazily so the module can be imported without settings initialised
        # (e.g. in tests that do not need a real Redis connection).
        import redis as sync_redis

        from fleet_platform.core.config import settings

        r = sync_redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        data: dict = r.hgetall(_SSH_REDIS_HASH)  # type: ignore[assignment]
        for raw_minion, raw_value in data.items():
            minion_id = raw_minion.decode() if isinstance(raw_minion, bytes) else str(raw_minion)
            try:
                value = float(raw_value.decode() if isinstance(raw_value, bytes) else raw_value)
            except (ValueError, AttributeError):
                value = 0.0
            node_ssh_reachable.labels(minion_id=minion_id).set(value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh_ssh_reachability_gauge: Redis read failed: %s", exc)


def refresh_node_count_gauges() -> None:
    """Query DB for node counts and update kri_nodes_total/online/offline gauges.

    Uses a short-lived synchronous DB session so it can be called from the
    synchronous /metrics handler.  Errors are swallowed — the scrape must not
    return HTTP 500.

    Issue #576: previously these gauges were always zero because nothing
    populated them.  This function is called from the /metrics endpoint before
    generate_latest() so every scrape reflects the real fleet state.
    """
    try:
        from sqlalchemy import func, select

        from fleet_platform.db.session import get_sync_db
        from fleet_platform.models.node import Node

        with get_sync_db() as db:
            rows = db.execute(select(Node.status, func.count().label("cnt")).group_by(Node.status)).all()

        counts: dict[str, int] = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
        for status, cnt in rows:
            if status in counts:
                counts[status] = cnt
            else:
                counts["unknown"] += cnt

        total = sum(counts.values())
        nodes_total.set(total)
        nodes_online.set(counts["online"])
        nodes_offline.set(counts["offline"] + counts["stale"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh_node_count_gauges: DB read failed: %s", exc)


def refresh_beat_heartbeat_gauge() -> None:
    """Read the Celery beat dead-man key and export it as a Unix timestamp gauge.

    ``kri_beat_last_run_timestamp_seconds`` is set to the epoch second of the
    last successful mark_stale_nodes run, or 0 if the key is absent (beat has
    been silent longer than _MAINTENANCE_HEARTBEAT_TTL = 600 s).

    Alertmanager rule ``KriBeatHeartbeatExpired`` fires when this gauge is 0
    or when ``time() - kri_beat_last_run_timestamp_seconds > 600``.

    Issue #576.
    """
    try:
        from datetime import UTC, datetime

        import redis as sync_redis

        from fleet_platform.core.config import settings

        r = sync_redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        raw = r.get(_MAINTENANCE_HEARTBEAT_KEY)
        if raw is None:
            beat_last_run_timestamp_seconds.set(0)
        else:
            ts_str = raw.decode() if isinstance(raw, bytes) else str(raw)
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            beat_last_run_timestamp_seconds.set(dt.timestamp())
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh_beat_heartbeat_gauge: Redis read failed: %s", exc)


def refresh_pending_action_queue_depth_gauge() -> None:
    """Query DB for pending/executing action count and update kri_pending_action_queue_depth.

    Uses a short-lived synchronous DB session.  Errors are swallowed — /metrics must
    never return HTTP 500.

    Issue #661 / audit #639.
    """
    try:
        from sqlalchemy import func, select

        from fleet_platform.db.session import get_sync_db
        from fleet_platform.models.pending_action import PendingAction

        with get_sync_db() as db:
            n = db.execute(
                select(func.count())
                .select_from(PendingAction)
                .where(PendingAction.status.in_(["pending", "executing"]))
            ).scalar_one()
        pending_action_queue_depth.set(n)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh_pending_action_queue_depth_gauge failed: %s", exc)


def refresh_embedding_staleness_gauge() -> None:
    """Query DB for the oldest embedding timestamp and export staleness as seconds.

    ``kri_embedding_index_staleness_seconds`` is the delta between now and the
    oldest ``embedded_at`` across all source types.  0 when no embeddings exist.

    Alert: > 3600 (index is over 1 hour stale — embed server may be down).

    Issue #1027.
    """
    try:
        from datetime import UTC, datetime

        from sqlalchemy import func, select

        from fleet_platform.db.session import get_sync_db
        from fleet_platform.models.fleet_embedding import FleetEmbedding

        with get_sync_db() as db:
            oldest = db.execute(select(func.min(FleetEmbedding.embedded_at))).scalar_one_or_none()

        if oldest is None:
            embedding_index_staleness_seconds.set(0)
        else:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            staleness = (datetime.now(UTC) - oldest).total_seconds()
            embedding_index_staleness_seconds.set(max(0, staleness))
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh_embedding_staleness_gauge failed: %s", exc)


def refresh_all_gauges() -> None:
    """Convenience wrapper — refresh every gauge that needs a scrape-time update.

    Called by the /metrics endpoint handler in main.py so all gauges are
    current on every Prometheus scrape.
    """
    refresh_ssh_reachability_gauge()
    refresh_node_count_gauges()
    refresh_beat_heartbeat_gauge()
    refresh_pending_action_queue_depth_gauge()
    refresh_embedding_staleness_gauge()
