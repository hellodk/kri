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

    Reads connection details from the default enabled SaltMaster row (#655).
    Marks nodes whose minion is in manage.up as online (refreshes last_seen_at).
    Nodes not seen in manage.up are left unchanged — the existing mark_stale_nodes
    task handles the stale→offline transition.
    """
    from fleet_platform.models.salt_master import SaltMaster
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    # Resolve connection details from the default enabled master in the DB.
    with get_sync_db() as db:
        master = db.execute(
            select(SaltMaster).where(SaltMaster.enabled.is_(True)).where(SaltMaster.is_default.is_(True))
        ).scalar_one_or_none()

        if master is None:
            return {"status": "skipped", "reason": "no default enabled salt master configured"}

        api_url: str = (master.api_url or "").rstrip("/")
        api_user: str = master.api_user or ""
        api_eauth: str = master.api_eauth or "pam"
        tls_verify: bool = bool(getattr(master, "tls_verify", False))

        if not api_url or not api_user:
            return {"status": "skipped", "reason": "api_url or api_user not configured on default master"}

        api_password = ""
        if master.api_password_enc:
            try:
                api_password = decrypt_secret(master.api_password_enc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("salt_presence: cannot decrypt api_password_enc: %s", exc)
                return {"status": "error", "reason": f"cannot decrypt api_password: {exc}"}

    up_minions = _runner_call(api_url, api_user, api_password, api_eauth, tls_verify, "manage.up")
    if up_minions is None:
        return {"status": "error", "reason": "salt-api unreachable"}

    if not up_minions:
        return {"status": "ok", "online": 0, "message": "no minions reported up"}

    now = datetime.now(UTC)
    updated = 0

    with get_sync_db() as db:
        result = db.execute(select(Node).where(Node.minion_id.in_(up_minions)))
        nodes = result.scalars().all()
        for node in nodes:
            if node.maintenance_mode:
                continue
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
