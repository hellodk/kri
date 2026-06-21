"""Agent quarantine filesystem — scaffolding (#710).

LLM-generated artifacts (playbooks, Salt states) are written to a per-session
quarantine directory and **never** auto-promoted into the live tree. This module
provides the path contract and safety primitives; the authoring tools, quota
sweeper and diff/promote flow are built on top in Phase D (#713) / E (#714).

Hard rules enforced here:
- root is configurable via ``AGENT_QUARANTINE_ROOT`` (default ``/srv/kri/agent-quarantine``),
- layout is ``<root>/<user>/<session>/`` with 0700 perms,
- user/session path components are validated against traversal / injection,
- a resolved artifact path must stay inside its session dir,
- symlinks are rejected.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

QUARANTINE_ROOT = Path(os.getenv("AGENT_QUARANTINE_ROOT", "/srv/kri/agent-quarantine"))

DIR_MODE = 0o700
# Quotas / TTL enforced by the Phase D sweeper; defined here as the contract.
SESSION_QUOTA_BYTES = 5 * 1024 * 1024
USER_QUOTA_BYTES = 50 * 1024 * 1024
TTL_SECONDS = 24 * 60 * 60

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._@-]+$")


class QuarantineError(ValueError):
    """Raised when a path component or artifact path violates the safety rules."""


def _safe_component(value: object, *, kind: str) -> str:
    s = str(value)
    if (
        not s
        or len(s) > 255
        or s in (".", "..")
        or "\x00" in s
        or "/" in s
        or "\\" in s
        or not _SAFE_COMPONENT.match(s)
    ):
        raise QuarantineError(f"unsafe {kind} component: {value!r}")
    return s


def _root(root: str | os.PathLike | None) -> Path:
    return (Path(root) if root is not None else QUARANTINE_ROOT).resolve()


def session_dir(user: object, session_id: object, *, root: str | os.PathLike | None = None) -> Path:
    """Resolve (without creating) the quarantine dir for a user+session.

    Raises QuarantineError if components are unsafe or the path escapes the root.
    """
    base = _root(root)
    u = _safe_component(user, kind="user")
    s = _safe_component(session_id, kind="session")
    path = (base / u / s).resolve()
    if not path.is_relative_to(base):
        raise QuarantineError("path escapes quarantine root")
    return path


def ensure_session_dir(user: object, session_id: object, *, root: str | os.PathLike | None = None) -> Path:
    """Create the session dir (and user dir) with 0700 perms; return its path."""
    path = session_dir(user, session_id, root=root)
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, DIR_MODE)
    os.chmod(path.parent, DIR_MODE)
    return path


def assert_within_session(
    artifact_path: str | os.PathLike,
    user: object,
    session_id: object,
    *,
    root: str | os.PathLike | None = None,
) -> Path:
    """Validate that ``artifact_path`` is a non-symlink file path inside the session dir."""
    raw = Path(artifact_path)
    if raw.is_symlink():
        raise QuarantineError("symlinks are not allowed in quarantine")
    sd = session_dir(user, session_id, root=root)
    resolved = raw.resolve()
    if not resolved.is_relative_to(sd):
        raise QuarantineError("artifact path is outside the session directory")
    return resolved


def dir_size_bytes(path: str | os.PathLike) -> int:
    """Total size of regular (non-symlink) files under ``path`` (0 if absent)."""
    p = Path(path)
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
