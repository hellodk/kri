# fleet_platform/workers/salt_tasks.py
"""Celery tasks for Salt state application and ad-hoc commands.

Security note (issue #82): The Docker socket is NOT mounted into the worker
container. Salt commands are dispatched via the Salt HTTP API (salt-api)
running in the salt-master container.  Set the following environment variables:

    SALT_API_URL      URL of salt-api, e.g. http://salt-master:8080
    SALT_API_USER     Username for salt-api (eauth: pam or auto)
    SALT_API_PASSWORD Password for salt-api user

If SALT_API_URL is not set the tasks will return an error explaining the
required setup — no silent fallback to docker exec is provided.
"""

import logging
import os
from typing import Any

import requests

from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SALT_API_URL = os.environ.get("SALT_API_URL", "").rstrip("/")
_SALT_API_USER = os.environ.get("SALT_API_USER", "")
_SALT_API_PASSWORD = os.environ.get("SALT_API_PASSWORD", "")
_SALT_API_EAUTH = os.environ.get("SALT_API_EAUTH", "pam")

# Allowlist of Salt functions that can be executed via the ad-hoc command API.
# This prevents operators from running arbitrary shell commands via cmd.run
# or other dangerous Salt modules.
_ALLOWED_SALT_FUNCTIONS: frozenset[str] = frozenset(
    {
        "state.apply",
        "state.highstate",
        "state.show_sls",
        "pkg.install",
        "pkg.remove",
        "pkg.list_pkgs",
        "pkg.upgrade",
        "pip.install",
        "pip.installed",
        "pip.list",
        "service.start",
        "service.stop",
        "service.restart",
        "service.status",
        "disk.usage",
        "disk.inodeusage",
        "status.loadavg",
        "status.meminfo",
        "grains.items",
        "grains.get",
        "test.ping",
        "test.version",
        "saltutil.sync_all",
        "saltutil.refresh_pillar",
    }
)


def _salt_api_not_configured_error() -> dict:
    return {
        "status": "error",
        "reason": (
            "Salt API is not configured. Set SALT_API_URL, SALT_API_USER, and "
            "SALT_API_PASSWORD environment variables on the worker. "
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

    Dispatches a single command using the salt-api /run endpoint (no session
    persistence needed — credentials are passed inline for simplicity).
    """
    if not _SALT_API_URL:
        return _salt_api_not_configured_error()

    payload: dict[str, Any] = {
        "client": "local",
        "tgt": target,
        "tgt_type": "list",
        "fun": function,
        "username": _SALT_API_USER,
        "password": _SALT_API_PASSWORD,
        "eauth": _SALT_API_EAUTH,
    }
    if args:
        payload["arg"] = args
    if kwarg:
        payload["kwarg"] = kwarg

    try:
        resp = requests.post(
            f"{_SALT_API_URL}/run",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("return", [{}])
        return {
            "status": "ok",
            "result": result,
        }
    except requests.HTTPError as exc:
        return {
            "status": "error",
            "reason": f"salt-api HTTP error: {exc} — response: {exc.response.text[:500]}",
        }
    except requests.ConnectionError as exc:
        return {
            "status": "error",
            "reason": (
                f"Cannot reach salt-api at {_SALT_API_URL}: {exc}. "
                "Check that SALT_API_URL is correct and the salt-master container "
                "is running the rest_cherrypy or rest_tornado netapi module."
            ),
        }
    except Exception as exc:
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

    Dispatches via Salt HTTP API (salt-api).  Requires SALT_API_URL,
    SALT_API_USER, and SALT_API_PASSWORD to be set on the worker.
    """
    if not _SALT_API_URL:
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
    if function not in _ALLOWED_SALT_FUNCTIONS:
        logger.error("run_salt_cmd: rejected disallowed function %r", function)
        return {
            "status": "error",
            "reason": f"Function '{function}' is not in the allowlist. "
            f"Allowed functions: {sorted(_ALLOWED_SALT_FUNCTIONS)}",
        }

    if not _SALT_API_URL:
        return _salt_api_not_configured_error()

    target = ",".join(target_minions)
    logger.info("run_salt_cmd: target=%s function=%s args=%s", target, function, args)
    return _run_salt_api(
        function=function,
        target=target,
        args=args,
        timeout=120,
    )
