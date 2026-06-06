# fleet_platform/api/metrics_collectors.py
"""Custom Prometheus metric collectors that bridge the worker-to-API gap.

The Celery worker writes SSH probe results to a Redis hash.  This module
reads those results on every /metrics scrape and refreshes the
``kri_node_ssh_reachable`` Gauge labels so that Prometheus sees current
per-node reachability values without any cross-process registry sharing.

Design constraints (issue #356):
- /metrics must never return HTTP 500.  All Redis errors are swallowed and
  logged at DEBUG level; the Gauge simply retains its last-known values.
- The Redis read uses a short socket timeout (1 s) to avoid blocking the
  scrape for a meaningful period if Redis is slow.
"""

from __future__ import annotations

import logging

from fleet_platform.metrics import node_ssh_reachable

logger = logging.getLogger(__name__)

_SSH_REDIS_HASH = "kri:ssh_reachable"


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
