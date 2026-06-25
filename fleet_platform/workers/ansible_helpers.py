# fleet_platform/workers/ansible_helpers.py
"""Private helper functions extracted from ansible_tasks.py.

These are pure utilities (no Celery task decorator) used by the task
implementations in ansible_tasks.py.  Keeping them here reduces the size of
that module without changing any observable behaviour.
"""

import logging
import os
import subprocess
from pathlib import Path

from fleet_platform.core.validators import MINION_ID_RE as _MINION_ID_RE

logger = logging.getLogger(__name__)

_DEFAULT_PILLAR_DIR = Path("/srv/salt/pillar")
_SSH_OS_DETECT_TIMEOUT = 15  # seconds — quick uname check before playbook run


def _scrub_token(text: str, token: str) -> str:
    """Replace raw node token with *** in stdout to prevent accidental log exposure."""
    if not token or not text:
        return text
    return text.replace(token, "***")


def _validate_minion_id(minion_id: str) -> str:
    """Validate minion ID to prevent path traversal and YAML injection."""
    if not _MINION_ID_RE.match(minion_id):
        raise ValueError(f"Invalid minion ID '{minion_id}': must match [a-zA-Z0-9._-]{{1,128}}")
    return minion_id


def _get_pillar_dir(db) -> Path:
    """Return the configured pillar directory, falling back to /srv/salt/pillar."""
    from sqlalchemy import select as _select

    from fleet_platform.models.platform_setting import PlatformSetting

    row = db.execute(_select(PlatformSetting).where(PlatformSetting.key == "pillar_dir")).scalar_one_or_none()
    if row and row.value:
        return Path(row.value)
    return _DEFAULT_PILLAR_DIR


def _detect_os_family(
    ssh_host: str, ssh_user: str, ssh_args_extra: list[str], ssh_password: str | None = None
) -> str | None:
    """Return 'Darwin' or 'Linux' by running `uname -s` over SSH.

    Returns None when the host is unreachable or the command fails.
    ``ssh_args_extra`` is a flat list of extra SSH option tokens (e.g.
    ['-i', '/path/key', '-o', 'StrictHostKeyChecking=accept-new']).
    When ``ssh_password`` is provided and no key is in ssh_args_extra, uses
    sshpass so password auth works without an interactive prompt.
    """
    using_password = ssh_password and not any(a == "-i" for a in ssh_args_extra)

    if using_password:
        # sshpass + ssh without BatchMode so password auth is allowed
        cmd = [
            "sshpass",
            "-e",
            "ssh",
            "-F",
            "/dev/null",
            "-o",
            f"ConnectTimeout={_SSH_OS_DETECT_TIMEOUT}",
            "-o",
            "NumberOfPasswordPrompts=1",
            *ssh_args_extra,
            f"{ssh_user}@{ssh_host}",
            "uname -s",
        ]
        env: dict[str, str] | None = {**os.environ, "SSHPASS": ssh_password or ""}
    else:
        cmd = [
            "ssh",
            "-F",
            "/dev/null",
            "-o",
            f"ConnectTimeout={_SSH_OS_DETECT_TIMEOUT}",
            "-o",
            "BatchMode=yes",
            *ssh_args_extra,
            f"{ssh_user}@{ssh_host}",
            "uname -s",
        ]
        env = None

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SSH_OS_DETECT_TIMEOUT + 5, env=env)
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning(
            "_detect_os_family: uname failed rc=%s ssh_host=%s stderr=%r",
            result.returncode,
            ssh_host,
            result.stderr[:200],
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning("_detect_os_family: SSH timed out to %s", ssh_host)
        return None
    except Exception as _exc:  # noqa: BLE001
        logger.warning("_detect_os_family: unexpected error for %s: %s", ssh_host, _exc)
        return None
