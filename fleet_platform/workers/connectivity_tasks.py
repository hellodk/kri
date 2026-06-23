# fleet_platform/workers/connectivity_tasks.py
"""Periodic SSH reachability probe for all registered nodes.

Architecture note (issue #356):
The Celery worker and the FastAPI process are separate OS processes.  A
Prometheus Gauge set inside this worker would live in the worker's
process-local registry and never appear in /metrics served by the API.
The bridge is Redis: this task writes results to the hash
``kri:ssh_reachable`` (field = minion_id, value = "0" or "1") and the
companion timestamp key ``kri:ssh_reachable:ts``.  The API side reads
those values on every /metrics request via
:func:`fleet_platform.api.metrics_collectors.refresh_ssh_reachability_gauge`
and sets the ``kri_node_ssh_reachable`` Gauge labels accordingly.

UI surfacing (#356-ui): in addition to the Redis/Prometheus bridge, each
sweep now persists a richer four-state result
(``ok`` / ``auth_failed`` / ``unreachable`` / ``unknown``) onto the node row
(``ssh_state`` / ``ssh_checked_at`` / ``ssh_detail``) so the Fleet Dashboard can
show SSH reachability without N per-node Redis reads. The actual probe lives in
:mod:`fleet_platform.services.ssh_probe` and is shared with the on-demand
``POST /api/v1/nodes/{id}/ssh-test`` endpoint.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import redis as sync_redis
from sqlalchemy import select

from fleet_platform.core.config import settings
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
from fleet_platform.services.ssh_probe import probe_node_ssh, ssh_state_to_reachable
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SSH_REDIS_HASH = "kri:ssh_reachable"
_SSH_REDIS_TS_KEY = "kri:ssh_reachable:ts"


@celery_app.task(
    name="fleet_platform.workers.connectivity_tasks.check_ssh_connectivity",
    queue="maintenance",
)
def check_ssh_connectivity() -> dict[str, Any]:
    """Probe SSH reachability for every node with a known IP.

    Runs every 15 minutes via beat (schedule=900).  For each node it persists the
    four-state result onto the node row and publishes the legacy 0/1 signal to the
    Redis hash ``kri:ssh_reachable`` for the ``kri_node_ssh_reachable`` gauge.

    Returns a summary dict: {"probed": N, "reachable": N, "unreachable": N}.
    """
    results: dict[str, int] = {}  # minion_id → 0/1 (legacy reachable signal)
    now = datetime.now(UTC)

    with get_sync_db() as db:
        nodes = db.execute(select(Node).where(Node.ip_address.isnot(None))).scalars().all()

        for node in nodes:
            try:
                creds = resolve_node_credentials_sync(node, db)
                probe = probe_node_ssh(node, creds)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "SSH connectivity probe error node=%s: %s — classifying as unreachable",
                    node.minion_id,
                    exc,
                )
                probe = {"state": "unreachable", "detail": f"probe error: {str(exc)[:120]}"}

            node.ssh_state = probe["state"]
            node.ssh_detail = probe.get("detail")
            node.ssh_checked_at = now
            results[node.minion_id] = ssh_state_to_reachable(probe["state"])

        # Persist the four-state results; a DB failure must not lose the Redis write.
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist SSH reachability to DB: %s", exc)
            db.rollback()

    # Persist to Redis — failure here must never abort the task result
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        for minion_id, value in results.items():
            r.hset(_SSH_REDIS_HASH, minion_id, str(value))
        r.set(_SSH_REDIS_TS_KEY, str(time.time()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write SSH reachability results to Redis: %s", exc)

    reachable_count = sum(v for v in results.values())
    return {
        "probed": len(results),
        "reachable": reachable_count,
        "unreachable": len(results) - reachable_count,
    }
