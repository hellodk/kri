# fleet_platform/workers/salt_tasks.py
"""Celery tasks for Salt state application and ad-hoc commands."""
import json
import subprocess
import logging

from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SALT_CONTAINER = "deploy-salt-master-1"


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
