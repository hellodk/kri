# fleet_platform/workers/salt_tasks.py
"""Celery tasks for Salt state application and ad-hoc commands."""
import json
import logging
import os
import shutil
import subprocess

from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Name of the salt-master container when running in Docker/Podman.
# Set to empty string for bare-metal deployments where salt is on PATH.
_SALT_MASTER_CONTAINER = os.environ.get("SALT_MASTER_CONTAINER", "deploy-salt-master-1")

# Ordered list of container runtime candidates to try.
_CONTAINER_RUNTIMES = ("docker", "podman")

# Common non-standard binary locations for Docker/Podman on macOS and Linux.
_EXTRA_PATHS = (
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
    "/snap/bin",
)


def _find_runtime() -> str | None:
    """Return the full path to docker or podman, checking both PATH and common locations."""
    for rt in _CONTAINER_RUNTIMES:
        found = shutil.which(rt)
        if found:
            return found
        for prefix in _EXTRA_PATHS:
            candidate = os.path.join(prefix, rt)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _salt_prefix() -> list[str]:
    """Return the command prefix for running salt.

    - Empty list  → salt is on PATH (bare-metal, salt-master on host)
    - [runtime, "exec", container] → proxy through docker/podman exec
    """
    if not _SALT_MASTER_CONTAINER:
        return []

    runtime = _find_runtime()
    if runtime:
        return [runtime, "exec", _SALT_MASTER_CONTAINER]

    # No container runtime found — try salt directly (may be installed on host).
    logger.warning(
        "No container runtime (docker/podman) found on PATH or common locations "
        "while SALT_MASTER_CONTAINER=%r is set. Attempting to run salt directly.",
        _SALT_MASTER_CONTAINER,
    )
    return []

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
    "pip.install",
    "pip.installed",
    "pip.list",
    "service.start",
    "service.stop",
    "service.restart",
    "service.status",
    "cmd.run",  # kept for operator flexibility; log a warning on use
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
})

# Ordered list of container runtime candidates to try.
_CONTAINER_RUNTIMES = ("docker", "podman")

# Common non-standard binary locations for Docker/Podman on macOS and Linux.
_EXTRA_PATHS = (
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
    "/snap/bin",
)


def _find_runtime() -> str | None:
    """Return the full path to docker or podman, checking both PATH and common locations."""
    for rt in _CONTAINER_RUNTIMES:
        found = shutil.which(rt)
        if found:
            return found
        for prefix in _EXTRA_PATHS:
            candidate = os.path.join(prefix, rt)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _salt_prefix() -> list[str]:
    """Return the command prefix for running salt.

    - Empty list  → salt is on PATH (bare-metal, salt-master on host)
    - [runtime, "exec", container] → proxy through docker/podman exec
    """
    if not _SALT_MASTER_CONTAINER:
        return []

    runtime = _find_runtime()
    if runtime:
        return [runtime, "exec", _SALT_MASTER_CONTAINER]

    # No container runtime found — try salt directly (may be installed on host).
    logger.warning(
        "SALT_MASTER_CONTAINER=%r but no container runtime (docker/podman) found on PATH "
        "or common locations. Attempting to run salt directly.",
        _SALT_MASTER_CONTAINER,
    )
    return []


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

    Works with Docker, Podman, or bare-metal salt installs. Runtime is detected
    automatically via SALT_MASTER_CONTAINER env var + shutil.which().
    """
    target = ",".join(target_minions)
    cmd = ["salt", "-L", target, "state.apply", state_name, "--no-color", "--out=json"]
    if pillar_data:
        cmd += [f"pillar={json.dumps(pillar_data)}"]

    full_cmd = _salt_prefix() + cmd
    logger.info("apply_salt_state: %s", " ".join(full_cmd))

    try:
        proc = subprocess.run(full_cmd, capture_output=True, text=True, timeout=300)
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "stdout": proc.stdout[:10000],
            "stderr": proc.stderr[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout after 300s"}
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "reason": (
                f"Salt runner not found ({exc}). "
                "Set SALT_MASTER_CONTAINER to the container name (docker/podman) "
                "or to empty string if salt is installed directly on the host."
            ),
        }
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

    full_cmd = _salt_prefix() + cmd
    logger.info("run_salt_cmd: %s", " ".join(full_cmd))

    try:
        proc = subprocess.run(full_cmd, capture_output=True, text=True, timeout=120)
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "stdout": proc.stdout[:10000],
            "stderr": proc.stderr[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout after 120s"}
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "reason": (
                f"Salt runner not found ({exc}). "
                "Set SALT_MASTER_CONTAINER to the container name (docker/podman) "
                "or to empty string if salt is installed directly on the host."
            ),
        }
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:500]}
