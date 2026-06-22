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

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

QUARANTINE_ROOT = Path(os.getenv("AGENT_QUARANTINE_ROOT", "/srv/kri/agent-quarantine"))

DIR_MODE = 0o700
FILE_MODE = 0o600
# Quotas / TTL enforced by the Phase D sweeper; defined here as the contract.
SESSION_QUOTA_BYTES = 5 * 1024 * 1024
USER_QUOTA_BYTES = 50 * 1024 * 1024
ARTIFACT_MAX_BYTES = 64 * 1024  # per-artifact hard cap (#713)
TTL_SECONDS = 24 * 60 * 60

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._@-]+$")
_META_SUFFIX = ".meta.json"


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


def user_dir(user: object, *, root: str | os.PathLike | None = None) -> Path:
    base = _root(root)
    u = _safe_component(user, kind="user")
    path = (base / u).resolve()
    if not path.is_relative_to(base):
        raise QuarantineError("path escapes quarantine root")
    return path


def write_artifact(
    user: object,
    session_id: object,
    filename: object,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    root: str | os.PathLike | None = None,
) -> dict[str, Any]:
    """Write one artifact into the session dir, enforcing per-artifact + per-session
    + per-user quotas. Rejects oversize content and quota overruns *before* writing.

    Returns the artifact descriptor (id, filename, size, created_at, metadata).
    """
    name = _safe_component(filename, kind="filename")
    if name.endswith(_META_SUFFIX):
        raise QuarantineError("filename may not use the reserved .meta.json suffix")
    data = content.encode("utf-8")
    if len(data) > ARTIFACT_MAX_BYTES:
        raise QuarantineError(f"artifact exceeds {ARTIFACT_MAX_BYTES}-byte cap ({len(data)} bytes)")

    sd = ensure_session_dir(user, session_id, root=root)
    target = assert_within_session(sd / name, user, session_id, root=root)

    # Quota check accounts for the delta if we are overwriting an existing file.
    existing = target.stat().st_size if target.exists() and not target.is_symlink() else 0
    session_after = dir_size_bytes(sd) - existing + len(data)
    if session_after > SESSION_QUOTA_BYTES:
        raise QuarantineError(f"session quota exceeded ({session_after} > {SESSION_QUOTA_BYTES})")
    ud = user_dir(user, root=root)
    user_after = dir_size_bytes(ud) - existing + len(data)
    if user_after > USER_QUOTA_BYTES:
        raise QuarantineError(f"user quota exceeded ({user_after} > {USER_QUOTA_BYTES})")

    target.write_bytes(data)
    os.chmod(target, FILE_MODE)

    meta = {
        "id": f"{_safe_component(session_id, kind='session')}:{name}",
        "filename": name,
        "size": len(data),
        "created_at": time.time(),
        "metadata": metadata or {},
    }
    meta_path = target.with_name(name + _META_SUFFIX)
    meta_path.write_text(json.dumps(meta))
    os.chmod(meta_path, FILE_MODE)
    return meta


def read_artifact(
    user: object,
    session_id: object,
    filename: object,
    *,
    root: str | os.PathLike | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (content, metadata) for one quarantined artifact."""
    name = _safe_component(filename, kind="filename")
    sd = session_dir(user, session_id, root=root)
    target = assert_within_session(sd / name, user, session_id, root=root)
    if not target.is_file():
        raise QuarantineError("artifact not found")
    content = target.read_text(errors="replace")
    meta_path = target.with_name(name + _META_SUFFIX)
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    return content, meta


def list_artifacts(user: object, *, root: str | os.PathLike | None = None) -> list[dict[str, Any]]:
    """List all quarantined artifacts for a user across their sessions (newest first)."""
    ud = user_dir(user, root=root)
    if not ud.exists():
        return []
    out: list[dict[str, Any]] = []
    for sess in ud.iterdir():
        if not sess.is_dir() or sess.is_symlink():
            continue
        for f in sess.iterdir():
            if not f.is_file() or f.is_symlink() or f.name.endswith(_META_SUFFIX):
                continue
            meta_path = f.with_name(f.name + _META_SUFFIX)
            meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
            out.append(
                {
                    "id": f"{sess.name}:{f.name}",
                    "session_id": sess.name,
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "created_at": meta.get("created_at"),
                    "metadata": meta.get("metadata", {}),
                }
            )
    out.sort(key=lambda a: a.get("created_at") or 0, reverse=True)
    return out


def sweep_expired(*, root: str | os.PathLike | None = None, now: float | None = None) -> list[str]:
    """Delete session dirs whose newest file is older than TTL_SECONDS.

    Returns the list of removed session paths. Idempotent; safe to run on a timer.
    """
    base = _root(root)
    if not base.exists():
        return []
    cutoff = (now if now is not None else time.time()) - TTL_SECONDS
    removed: list[str] = []
    for user_path in base.iterdir():
        if not user_path.is_dir() or user_path.is_symlink():
            continue
        for sess in user_path.iterdir():
            if not sess.is_dir() or sess.is_symlink():
                continue
            files = [f for f in sess.rglob("*") if f.is_file() and not f.is_symlink()]
            newest = max((f.stat().st_mtime for f in files), default=sess.stat().st_mtime)
            if newest < cutoff:
                shutil.rmtree(sess, ignore_errors=True)
                removed.append(str(sess))
    return removed
