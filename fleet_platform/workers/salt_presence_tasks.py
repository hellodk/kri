"""Celery task: sync node presence from salt-run manage.up/down (#254).

Calls salt-api runner client to get the list of connected (up) and
disconnected (down) minions. Marks nodes online/offline accordingly.
This runs every 90 seconds so nodes appear online within ~90s of their
salt-minion connecting, without waiting for a full grain report.
"""
import logging
import os
from datetime import UTC, datetime

import requests
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SALT_API_URL = os.environ.get("SALT_API_URL", "").rstrip("/")
_SALT_API_USER = os.environ.get("SALT_API_USER", "")
_SALT_API_PASSWORD = os.environ.get("SALT_API_PASSWORD", "")
_SALT_API_EAUTH = os.environ.get("SALT_API_EAUTH", "pam")


def _runner_call(fun: str, timeout: int = 30) -> list[str] | None:
    """Call a salt-run function via salt-api runner client.

    Returns a list of minion IDs, or None on error / not configured.
    """
    if not _SALT_API_URL:
        return None
    try:
        resp = requests.post(
            f"{_SALT_API_URL}/run",
            json={
                "client": "runner",
                "fun": fun,
                "username": _SALT_API_USER,
                "password": _SALT_API_PASSWORD,
                "eauth": _SALT_API_EAUTH,
            },
            timeout=timeout,
            verify=False,  # noqa: S501 — salt-api may use self-signed cert in lab
        )
        resp.raise_for_status()
        data = resp.json()
        # manage.up returns {"return": [["minion1", "minion2", ...]]}
        # The inner list may be a list of minion IDs
        result = data.get("return", [{}])
        if result and isinstance(result, list):
            inner = result[0]
            if isinstance(inner, list):
                return [str(m) for m in inner]
            if isinstance(inner, dict):
                return list(inner.keys())
        return []
    except Exception as exc:
        logger.debug("salt_presence: runner call %s failed: %s", fun, exc)
        return None


@celery_app.task(
    name="fleet_platform.workers.salt_presence_tasks.sync_minion_presence",
    queue="maintenance",
)
def sync_minion_presence() -> dict:
    """Sync node online/offline status from salt-run manage.up.

    Marks nodes whose minion is in manage.up as online (refreshes last_seen_at).
    Nodes not seen in manage.up are left unchanged — the existing mark_stale_nodes
    task handles the stale→offline transition.
    """
    if not _SALT_API_URL:
        return {"status": "skipped", "reason": "SALT_API_URL not configured"}

    up_minions = _runner_call("manage.up")
    if up_minions is None:
        return {"status": "error", "reason": "salt-api unreachable"}

    if not up_minions:
        return {"status": "ok", "online": 0, "message": "no minions reported up"}

    now = datetime.now(UTC)
    updated = 0

    with get_sync_db() as db:
        result = db.execute(
            select(Node).where(Node.minion_id.in_(up_minions))
        )
        nodes = result.scalars().all()
        for node in nodes:
            node.status = "online"
            node.last_seen_at = now
            updated += 1
        if nodes:
            db.commit()

    logger.info(
        "salt_presence: marked %d/%d reported-up nodes as online",
        updated,
        len(up_minions),
    )
    return {"status": "ok", "online": updated, "up_minions": len(up_minions)}
