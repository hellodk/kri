# fleet_platform/workers/salt_tasks.py
"""Celery tasks for Salt state application and ad-hoc commands.

Security note (issue #82): The Docker socket is NOT mounted into the worker
container. Salt commands are dispatched via the Salt HTTP API (salt-api)
running in the salt-master container.

Credentials are resolved from the default SaltMaster row in the DB (#562).
The legacy SALT_API_URL / SALT_API_USER / SALT_API_PASSWORD env vars are
retired — configure a salt master in Settings → Salt Masters instead.

If no default SaltMaster row exists the tasks return an error explaining the
required setup — no silent fallback is provided.
"""

import logging
from typing import Any

import requests
from sqlalchemy import select

from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.platform_settings_svc import (
    decrypt_secret,
    get_allowed_salt_functions_sync,
)
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_default_master():
    """Return the default SaltMaster ORM row (or None) from the DB.

    Looks for the row where is_default=True.  If none is default, returns the
    single enabled master.  Returns None when no master is configured at all.
    """
    from fleet_platform.db.session import get_sync_db

    with get_sync_db() as db:
        # Prefer explicit default
        row = db.execute(
            select(SaltMaster).where(SaltMaster.is_default.is_(True)).where(SaltMaster.enabled.is_(True)).limit(1)
        ).scalar_one_or_none()
        if row is not None:
            return _extract_master_creds(row)

        # Fall back to any single enabled master
        row = db.execute(select(SaltMaster).where(SaltMaster.enabled.is_(True)).limit(1)).scalar_one_or_none()
        if row is not None:
            return _extract_master_creds(row)

        return None


def _extract_master_creds(master: SaltMaster) -> dict:
    """Extract the fields needed by _run_salt_api from an ORM row (while in-session)."""
    password = ""
    if master.api_password_enc:
        try:
            password = decrypt_secret(master.api_password_enc)
        except Exception:
            logger.warning("salt_tasks: failed to decrypt api_password_enc for master %s", master.id)

    return {
        "api_url": master.api_url or "",
        "api_user": master.api_user or "",
        "api_password": password,
        "api_eauth": master.api_eauth or "pam",
        "tls_verify": master.tls_verify,
    }


def _salt_api_not_configured_error() -> dict:
    return {
        "status": "error",
        "reason": (
            "No salt-master configured — add one in Settings → Salt Masters. "
            "The Docker socket is intentionally not mounted (security issue #82). "
            "To enable salt-api on the salt-master container, add the rest_cherrypy "
            "netapi module and configure it in salt-master.conf."
        ),
    }


def _run_salt_api(
    function: str,
    target: str,
    args: list[str] | None = None,
    kwarg: dict[str, Any] | None = None,
    timeout: int = 300,
) -> dict:
    """Execute a Salt function via the HTTP API.

    Resolves credentials from the default SaltMaster DB row (#562).
    """
    creds = _get_default_master()
    if creds is None or not creds.get("api_url"):
        return _salt_api_not_configured_error()

    _url = creds["api_url"].rstrip("/")

    payload: dict[str, Any] = {
        "client": "local",
        "tgt": target,
        "tgt_type": "list",
        "fun": function,
        "username": creds["api_user"],
        "password": creds["api_password"],
        "eauth": creds["api_eauth"],
    }
    if args:
        payload["arg"] = args
    if kwarg:
        payload["kwarg"] = kwarg

    try:
        resp = requests.post(
            f"{_url}/run",
            json=payload,
            timeout=timeout,
            verify=creds["tls_verify"],
        )
        resp.raise_for_status()
        result = resp.json().get("return", [{}])
        return {
            "status": "ok",
            "result": result,
        }
    except requests.HTTPError as exc:
        logger.error(
            "salt_tasks: salt-api HTTP error for function %r: %s",
            function,
            exc.response.text[:500] if exc.response is not None else "(no response body)",
        )
        return {
            "status": "error",
            "reason": (
                f"salt-api HTTP error: {exc} — "
                f"response: {exc.response.text[:500] if exc.response is not None else '(no response body)'}"
            ),
        }
    except requests.ConnectionError as exc:
        logger.error("salt_tasks: cannot reach salt-api at %s: %s", _url, exc)
        return {
            "status": "error",
            "reason": (
                f"Cannot reach salt-api at {_url}: {exc}. "
                "Check that the salt-master is configured in Settings → Salt Masters "
                "and the salt-api service is running."
            ),
        }
    except Exception as exc:
        logger.warning("salt_tasks: unexpected error calling salt-api function %r: %s", function, exc)
        return {"status": "error", "reason": str(exc)[:500]}


@celery_app.task(
    name="fleet_platform.workers.salt_tasks.apply_salt_state",
    bind=True,
    queue="maintenance",
)
def apply_salt_state(
    self,
    state_name: str,
    target_minions: list[str],
    pillar_data: dict | None = None,
) -> dict:
    """Run: salt -L '{minion1,minion2}' state.apply {state_name} [pillar={...}]

    Dispatches via Salt HTTP API (salt-api).  Requires a default SaltMaster row
    with api_url / api_user / api_password_enc to be configured in the DB.
    """
    creds = _get_default_master()
    if creds is None or not creds.get("api_url"):
        return _salt_api_not_configured_error()

    target = ",".join(target_minions)
    kwarg: dict[str, Any] | None = None
    if pillar_data:
        kwarg = {"pillar": pillar_data}

    logger.info(
        "apply_salt_state: target=%s state=%s pillar=%s",
        target,
        state_name,
        bool(pillar_data),
    )
    return _run_salt_api(
        function="state.apply",
        target=target,
        args=[state_name],
        kwarg=kwarg,
        timeout=300,
    )


@celery_app.task(
    name="fleet_platform.workers.salt_tasks.run_salt_cmd",
    bind=True,
    queue="maintenance",
)
def run_salt_cmd(
    self,
    function: str,
    target_minions: list[str],
    args: list[str] | None = None,
) -> dict:
    """Run: salt -L '{minion1,minion2}' {function} [args...]"""
    from fleet_platform.db.session import get_sync_db

    with get_sync_db() as db:
        allowed = get_allowed_salt_functions_sync(db)
    if function not in allowed:
        logger.error("run_salt_cmd: rejected disallowed function %r", function)
        return {
            "status": "error",
            "reason": f"Function '{function}' is not in the allowlist. Allowed functions: {sorted(allowed)}",
        }

    creds = _get_default_master()
    if creds is None or not creds.get("api_url"):
        return _salt_api_not_configured_error()

    target = ",".join(target_minions)
    logger.info("run_salt_cmd: target=%s function=%s args=%s", target, function, args)
    return _run_salt_api(
        function=function,
        target=target,
        args=args,
        timeout=120,
    )


def _status_from_salt_result(result) -> str:
    """Map a run_salt_cmd return value to a pending-action status."""
    if isinstance(result, dict) and result.get("status") == "error":
        return "failed"
    return "executed"


@celery_app.task(name="finalize_node_action", queue="maintenance")
def finalize_node_action(salt_result, action_id: str) -> dict:
    """Celery callback (link) for run_salt_cmd: record the real execution outcome
    on the PendingAction. Receives run_salt_cmd's return value as the first arg.

    Routed to the 'maintenance' queue so the worker (--queues default,maintenance,…)
    actually consumes it.  Before #640 this used the default 'celery' queue which
    no worker consumed — every action was stuck in 'executing' forever.

    Guard: only finalises an action that is still 'executing'.  A later status
    (e.g. reaped to 'failed') must not be clobbered by a stale callback."""
    import uuid as _uuid
    from datetime import UTC, datetime

    from fleet_platform.db.session import get_sync_db
    from fleet_platform.models.pending_action import PendingAction

    new_status = _status_from_salt_result(salt_result)
    with get_sync_db() as db:
        action = db.get(PendingAction, _uuid.UUID(action_id))
        if action is None:
            return {"status": "not_found", "action_id": action_id}
        if action.status != "executing":
            return {"status": "noop", "current": action.status, "action_id": action_id}
        action.status = new_status
        action.executed_at = datetime.now(UTC)
        db.commit()
    return {"status": new_status, "action_id": action_id}
