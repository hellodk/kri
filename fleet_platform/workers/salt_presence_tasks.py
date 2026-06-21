"""Celery task: sync node presence from salt-run manage.up/down (#254, #655).

Calls salt-api runner client to get the list of connected (up) minions.
Marks nodes online accordingly.  This runs every 90 seconds so nodes appear
online within ~90s of their salt-minion connecting, without waiting for a full
grain report.

Connection details are read from the default enabled SaltMaster row in the DB
(#655 — replaces the old env-var approach that broke when SALT_API_URL was unset).
"""

import logging
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_RUNNER_TIMEOUT = 30  # seconds


def _runner_call(
    api_url: str,
    api_user: str,
    api_password: str,
    api_eauth: str,
    tls_verify: bool,
    fun: str,
) -> list[str] | None:
    """Call a salt-run function via salt-api runner client.

    Returns a list of minion IDs, or None on error / unreachable.
    """
    try:
        resp = requests.post(
            f"{api_url}/run",
            json={
                "client": "runner",
                "fun": fun,
                "username": api_user,
                "password": api_password,
                "eauth": api_eauth,
            },
            timeout=_RUNNER_TIMEOUT,
            verify=tls_verify,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        # manage.up returns {"return": [["minion1", "minion2", ...]]}
        result = data.get("return", [{}])
        if result and isinstance(result, list):
            inner = result[0]
            if isinstance(inner, list):
                return [str(m) for m in inner]
            if isinstance(inner, dict):
                return list(inner.keys())
        return []
    except Exception as exc:
        logger.warning("salt_presence: runner call %s failed: %s", fun, exc)
        return None


@celery_app.task(
    name="fleet_platform.workers.salt_presence_tasks.sync_minion_presence",
    queue="maintenance",
)
def sync_minion_presence() -> dict:
    """Sync node online/offline status from salt-run manage.up.

    Polls EVERY enabled SaltMaster (not just the default) and unions the
    reported-up minions (#689). Under multi-master failover a minion may be
    attached to any enabled master — a minion up on ANY master is online.
    Marks matching nodes online (refreshes last_seen_at). Nodes not seen are
    left unchanged — mark_stale_nodes handles the stale→offline transition.
    """
    from fleet_platform.models.salt_master import SaltMaster
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    # Snapshot connection details for all enabled masters while the session is
    # open (avoid lazy-load after it closes).
    with get_sync_db() as db:
        masters = db.execute(select(SaltMaster).where(SaltMaster.enabled.is_(True))).scalars().all()

        if not masters:
            return {"status": "skipped", "reason": "no enabled salt master configured"}

        master_conns: list[dict[str, Any]] = []
        for master in masters:
            api_url = (master.api_url or "").rstrip("/")
            api_user = master.api_user or ""
            if not api_url or not api_user:
                continue
            api_password = ""
            if master.api_password_enc:
                try:
                    api_password = decrypt_secret(master.api_password_enc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("salt_presence: cannot decrypt api_password for master %s: %s", master.name, exc)
                    continue
            master_conns.append(
                {
                    "id": master.id,
                    "is_default": bool(getattr(master, "is_default", False)),
                    "name": master.name,
                    "api_url": api_url,
                    "api_user": api_user,
                    "api_password": api_password,
                    "api_eauth": master.api_eauth or "pam",
                    "tls_verify": bool(getattr(master, "tls_verify", False)),
                }
            )

    if not master_conns:
        return {"status": "skipped", "reason": "no enabled master has api_url + api_user configured"}

    # Union manage.up across all enabled masters. One unreachable master must not
    # abort the sweep — the others are still polled.
    #
    # We also record which master(s) reported each minion (#707) so we can fix
    # node.salt_master_id when it points at a master that no longer owns the
    # minion (e.g. the migration-041 backfill pinned everything to the first
    # master). Online semantics stay "up on ANY master" (#689).
    up_minions: set[str] = set()
    minion_reporters: dict[str, list[dict[str, Any]]] = {}
    reachable = 0
    for conn in master_conns:
        result = _runner_call(
            conn["api_url"],
            conn["api_user"],
            conn["api_password"],
            conn["api_eauth"],
            conn["tls_verify"],
            "manage.up",
        )
        if result is None:
            continue
        reachable += 1
        up_minions.update(result)
        for minion_id in result:
            minion_reporters.setdefault(minion_id, []).append({"id": conn["id"], "is_default": conn["is_default"]})

    if reachable == 0:
        return {"status": "error", "reason": "no enabled salt master reachable"}

    if not up_minions:
        return {"status": "ok", "online": 0, "message": "no minions reported up", "masters": reachable}

    now = datetime.now(UTC)
    updated = 0
    reassigned = 0

    with get_sync_db() as db:
        result_nodes = db.execute(select(Node).where(Node.minion_id.in_(up_minions)))
        nodes = result_nodes.scalars().all()
        for node in nodes:
            if node.maintenance_mode:
                continue
            node.status = "online"
            node.last_seen_at = now
            updated += 1

            # Attribute the node to a master that actually reported it. Only
            # touch salt_master_id when it is unset or stale (its current master
            # did not report this minion this cycle). Prefer the default master
            # when more than one reported it.
            reporters = minion_reporters.get(node.minion_id, [])
            if reporters:
                reporter_ids = [r["id"] for r in reporters]
                if node.salt_master_id is None or node.salt_master_id not in reporter_ids:
                    chosen = next((r["id"] for r in reporters if r["is_default"]), reporter_ids[0])
                    if node.salt_master_id != chosen:
                        node.salt_master_id = chosen
                        reassigned += 1
        if nodes:
            db.commit()

    logger.info(
        "salt_presence: marked %d nodes online (%d reassigned) from %d/%d reachable master(s)",
        updated,
        reassigned,
        reachable,
        len(master_conns),
    )
    return {
        "status": "ok",
        "online": updated,
        "reassigned": reassigned,
        "up_minions": len(up_minions),
        "masters": reachable,
    }
