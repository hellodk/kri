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

Probe classification:
- TCP connect to port 22 within 5 s: if this fails → 0 (no further check).
- If ``auth_mode == "key"`` **and** an SSH key is available: attempt
  ``ssh -o BatchMode=yes -o ConnectTimeout=5 -i <tmpkey> user@ip true``
  via subprocess.  returncode 0 → 1, anything else → 0.
- Password mode or no key: TCP success alone → 1 (we cannot BatchMode-test
  password auth without pexpect; TCP reachability is the useful signal).
- Any unhandled exception in a per-node probe → 0 for that node; the sweep
  continues for all remaining nodes.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess  # nosec B404 — controlled SSH probe, no shell=True
import tempfile
import time
from typing import Any

import redis as sync_redis
from sqlalchemy import select

from fleet_platform.core.config import settings
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SSH_REDIS_HASH = "kri:ssh_reachable"
_SSH_REDIS_TS_KEY = "kri:ssh_reachable:ts"
_TCP_TIMEOUT = 5  # seconds


def _probe_node(node: Node, creds: dict) -> int:
    """Return 1 if node is reachable via SSH, 0 otherwise.

    Never raises — all exceptions are caught and logged.
    """
    ip = node.ip_address
    try:
        # Step 1: TCP connect to port 22
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(_TCP_TIMEOUT)
        rc = sock.connect_ex((str(ip), 22))
        sock.close()
        if rc != 0:
            logger.debug("SSH probe TCP failure node=%s ip=%s rc=%d", node.minion_id, ip, rc)
            return 0

        # Step 2: if we have a key, attempt a real auth-level check
        ssh_key = creds.get("ssh_key", "")
        auth_mode = creds.get("auth_mode", "password")
        if auth_mode == "key" and ssh_key:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=True) as tmp:
                tmp.write(ssh_key)
                tmp.flush()
                os.chmod(tmp.name, 0o600)
                proc = subprocess.run(  # nosec B603 B607 — fixed args, no shell
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        f"ConnectTimeout={_TCP_TIMEOUT}",
                        "-o",
                        "StrictHostKeyChecking=no",
                        "-i",
                        tmp.name,
                        f"{creds.get('ssh_user', 'admin')}@{ip}",
                        "true",
                    ],
                    capture_output=True,
                    timeout=_TCP_TIMEOUT + 2,
                )
                if proc.returncode != 0:
                    logger.debug(
                        "SSH auth probe failed node=%s rc=%d stderr=%s",
                        node.minion_id,
                        proc.returncode,
                        proc.stderr[:200] if proc.stderr else b"",
                    )
                    return 0

        return 1

    except Exception as exc:  # noqa: BLE001
        logger.debug("SSH probe exception node=%s: %s", node.minion_id, exc)
        return 0


@celery_app.task(
    name="fleet_platform.workers.connectivity_tasks.check_ssh_connectivity",
    queue="maintenance",
)
def check_ssh_connectivity() -> dict[str, Any]:
    """Probe SSH reachability for every node with a known IP and write results to Redis.

    Runs every 15 minutes via beat (schedule=900).  Results are published to
    the Redis hash ``kri:ssh_reachable`` so the API /metrics endpoint can
    expose them as the ``kri_node_ssh_reachable`` Prometheus Gauge without
    any cross-process registry sharing.

    Returns a summary dict: {"probed": N, "reachable": N, "unreachable": N}.
    """
    results: dict[str, int] = {}  # minion_id → 0/1

    with get_sync_db() as db:
        nodes = db.execute(select(Node).where(Node.ip_address.isnot(None))).scalars().all()

        for node in nodes:
            try:
                creds = resolve_node_credentials_sync(node, db)
                reachable = _probe_node(node, creds)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "SSH connectivity probe error node=%s: %s — classifying as unreachable",
                    node.minion_id,
                    exc,
                )
                reachable = 0
            results[node.minion_id] = reachable

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
