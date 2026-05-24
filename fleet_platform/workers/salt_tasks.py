# fleet_platform/workers/salt_tasks.py
"""Celery tasks for Salt state application and ad-hoc commands."""
import json
import logging
import os
import subprocess

from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SALT_CONTAINER = os.environ.get("SALT_MASTER_CONTAINER", "deploy-salt-master-1")

# Allowlist of Salt functions that can be executed via the ad-hoc command API.
# This prevents operators from running arbitrary shell commands via cmd.run
# or other dangerous Salt modules.
_ALLOWED_SALT_FUNCTIONS: frozenset[str] = frozenset({
    "state.apply",
    "state.highstate",
    "state.show_sls",
    "pkg.install",
    "pkg.remove",
    "pkg.list_pkgs",
    "pkg.upgrade",
    "service.start",
    "service.stop",
    "service.restart",
    "service.status",
    "cmd.run",  # kept for operator flexibility; log a warning on use
    "grains.items",
    "grains.get",
    "test.ping",
    "test.version",
    "saltutil.sync_all",
    "saltutil.refresh_pillar",
})


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

    The salt binary lives inside the salt-master container; we invoke it via
    docker exec so the worker doesn't need Salt installed.
    """
    target = ",".join(target_minions)
    cmd = ["salt", "-L", target, "state.apply", state_name, "--no-color", "--out=json"]
    if pillar_data:
        cmd += [f"pillar={json.dumps(pillar_data)}"]

    docker_cmd = ["docker", "exec", _SALT_CONTAINER] + cmd
    logger.info("apply_salt_state: %s", " ".join(docker_cmd))

    try:
        proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=300)
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "stdout": proc.stdout[:10000],
            "stderr": proc.stderr[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout after 300s"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:500]}


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
    if function == "cmd.run":
        logger.warning(
            "run_salt_cmd: cmd.run invoked on minions=%r args=%r — ensure this is intentional",
            target_minions,
            args,
        )
    target = ",".join(target_minions)
    cmd = ["salt", "-L", target, function, "--no-color", "--out=json"]
    if args:
        cmd += args

    docker_cmd = ["docker", "exec", _SALT_CONTAINER] + cmd
    logger.info("run_salt_cmd: %s", " ".join(docker_cmd))

    try:
        proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=120)
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "stdout": proc.stdout[:10000],
            "stderr": proc.stderr[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout after 120s"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:500]}
