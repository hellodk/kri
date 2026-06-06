"""Hardened git subprocess environment and error classification (#377).

Token credentials are passed via a GIT_ASKPASS helper script — they never
appear in argv or the clone URL.  SSH keys are written to a 0600 temp file
wired into GIT_SSH_COMMAND.  All temp files are unlinked on context exit.
"""

import logging
import os
import stat
import tempfile
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# askpass helper script
# ---------------------------------------------------------------------------

_ASKPASS = """#!/bin/sh
case "$1" in
  [Uu]sername*) printf '%s\\n' "$KRI_GIT_USER" ;;
  *) printf '%s\\n' "$KRI_GIT_PASS" ;;
esac
"""

# ---------------------------------------------------------------------------
# Error classification markers
# ---------------------------------------------------------------------------

AUTH_MARKERS = (
    "could not read username",
    "terminal prompts disabled",
    "authentication failed",
    "permission denied (publickey)",
    "invalid username or token",
    "authorization failed",
    "http basic: access denied",
)

UNREACHABLE_MARKERS = (
    "could not resolve host",
    "connection refused",
    "connection timed out",
    "timed out",
    "network is unreachable",
    "no route to host",
    "connection reset",
)

NOT_FOUND_MARKERS = (
    "repository not found",
    "not found",
)


def classify_git_error(stderr: str) -> str:
    """Classify a git error string.

    Returns one of: ``auth_required``, ``unreachable``, ``not_found``, ``other``.
    Checks in that priority order so that auth errors take precedence over
    "not found" (a private repo returns 404 *and* an auth error on some hosts).
    """
    lower = stderr.lower()
    for marker in AUTH_MARKERS:
        if marker in lower:
            return "auth_required"
    for marker in UNREACHABLE_MARKERS:
        if marker in lower:
            return "unreachable"
    for marker in NOT_FOUND_MARKERS:
        if marker in lower:
            return "not_found"
    return "other"


def redact_secrets(text: str, secrets: list) -> str:
    """Replace every non-empty secret string in *text* with ``'***'``."""
    for secret in secrets:
        if not secret:
            continue
        text = text.replace(str(secret), "***")
    return text


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@contextmanager
def git_auth_env(
    token: str | None = None,
    ssh_key: str | None = None,
) -> Generator[dict, None, None]:
    """Yield an environment dict for git subprocesses.

    * Always sets ``GIT_TERMINAL_PROMPT=0`` so git never blocks waiting for
      a TTY prompt.
    * Always sets ``GIT_SSH_COMMAND`` with ``-o BatchMode=yes`` so SSH also
      never blocks.
    * If *token* is provided: writes a GIT_ASKPASS helper script to a temp
      file (mode 0700) and sets ``KRI_GIT_USER=x-access-token`` /
      ``KRI_GIT_PASS=<token>`` in the env.  The token is **never** embedded
      in a URL or any other env var.
    * If *ssh_key* is provided: writes the PEM content to a temp file (mode
      0600) and wires it into ``GIT_SSH_COMMAND`` via ``-i <path>``.
    * All temp files are unlinked on context exit regardless of exceptions.
    """
    tmp_files: list[str] = []

    env = {**os.environ}
    env["GIT_TERMINAL_PROMPT"] = "0"

    ssh_cmd_parts = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no"]

    try:
        if ssh_key:
            fd, key_path = tempfile.mkstemp(prefix="kri-ssh-", suffix=".pem")
            tmp_files.append(key_path)
            try:
                os.write(fd, ssh_key.encode())
            finally:
                os.close(fd)
            os.chmod(key_path, 0o600)
            ssh_cmd_parts += ["-i", key_path]

        env["GIT_SSH_COMMAND"] = " ".join(ssh_cmd_parts)

        if token:
            fd, askpass_path = tempfile.mkstemp(prefix="kri-askpass-", suffix=".sh")
            tmp_files.append(askpass_path)
            try:
                os.write(fd, _ASKPASS.encode())
            finally:
                os.close(fd)
            os.chmod(askpass_path, stat.S_IRWXU)  # 0700
            env["GIT_ASKPASS"] = askpass_path
            env["KRI_GIT_USER"] = "x-access-token"
            env["KRI_GIT_PASS"] = token

        yield env

    finally:
        for path in tmp_files:
            try:
                os.unlink(path)
            except OSError:
                logger.debug("git_auth_env: could not unlink temp file %s", path)
