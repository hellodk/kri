"""Manage external playbook sources (extra dirs + git repos)."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from fleet_platform.services.git_auth import git_auth_env
from fleet_platform.services.platform_settings_svc import decrypt_secret

logger = logging.getLogger(__name__)

# Git repo cache stored under ~/.kri/git-repos (not /tmp) to survive restarts
# and avoid temp-directory security warnings (CWE-377).
_GIT_CACHE_DIR = Path(os.environ.get("KRI_GIT_CACHE", str(Path.home() / ".kri" / "git-repos")))


def _translate_path(host_path: str) -> str:
    """Translate a host-side path to its container equivalent using PLAYBOOK_PATH_MAP.

    The env var format is ``host_prefix:container_prefix`` with multiple
    entries separated by commas, e.g.::

        PLAYBOOK_PATH_MAP=/home/dk/Documents/git/pulse:/mnt/pulse,/data:/mnt/data

    The first matching prefix wins.  If no mapping matches the path is
    returned unchanged.
    """
    raw_map = os.environ.get("PLAYBOOK_PATH_MAP", "").strip()
    if not raw_map:
        return host_path

    for entry in raw_map.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        # Split on the *first* colon only so Windows-style paths survive
        colon_idx = entry.index(":")
        host_prefix = entry[:colon_idx]
        container_prefix = entry[colon_idx + 1 :]
        if host_path.startswith(host_prefix):
            translated = container_prefix + host_path[len(host_prefix) :]
            logger.debug(
                "playbook path translated: %s → %s (map entry: %s:%s)",
                host_path,
                translated,
                host_prefix,
                container_prefix,
            )
            return translated

    return host_path


def _default_clone_path(url: str) -> str:
    repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    return str(_GIT_CACHE_DIR / repo_name)


def _clone_git_source(
    url: str,
    branch: str,
    local_path: str,
    token: str | None = None,
    ssh_key: str | None = None,
) -> Path:
    """Clone a git repo for the first time. Does NOT pull — use _pull_git_source for updates."""
    p = Path(local_path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        with git_auth_env(token=token, ssh_key=ssh_key) as env:
            subprocess.run(
                ["git", "clone", "--depth=1", "--branch", branch, url, str(p)],
                check=True,
                capture_output=True,
                timeout=60,
                env=env,
            )
    return p


def _pull_git_source(
    local_path: str,
    token: str | None = None,
    ssh_key: str | None = None,
) -> None:
    """Pull latest changes into an already-cloned repo."""
    with git_auth_env(token=token, ssh_key=ssh_key) as env:
        subprocess.run(
            ["git", "-C", local_path, "pull", "--ff-only"],
            check=False,
            capture_output=True,
            timeout=30,
            env=env,
        )


def _resolve_source_credentials(src: dict) -> tuple[str | None, str | None]:
    """Return (token, ssh_key) for a git source dict.

    Priority:
    1. ``credential_id`` key → look up Credential row via sync DB session.
    2. Legacy ``token_enc`` / ``ssh_key_enc`` keys → decrypt in-place.
    3. Neither present → (None, None).
    """
    credential_id = src.get("credential_id")
    if credential_id:
        try:
            import uuid as _uuid

            from sqlalchemy import select as _select

            from fleet_platform.db.session import get_sync_db
            from fleet_platform.models.credential import Credential

            _cred_uuid = _uuid.UUID(str(credential_id))
            with get_sync_db() as db:
                row = db.execute(_select(Credential).where(Credential.id == _cred_uuid)).scalar_one_or_none()
            if row is None:
                logger.warning("credential_id %s not found — skipping auth", credential_id)
                return None, None
            secret = decrypt_secret(row.secret_enc)
            if row.kind in ("token", "username_password"):
                return secret, None
            elif row.kind == "ssh_key":
                return None, secret
        except Exception as exc:
            logger.error("failed to resolve credential %s: %s", credential_id, exc)
            return None, None

    token: str | None = None
    ssh_key: str | None = None
    if src.get("token_enc"):
        try:
            token = decrypt_secret(src["token_enc"])
        except Exception as exc:
            logger.error("failed to decrypt token_enc: %s", exc)
    if src.get("ssh_key_enc"):
        try:
            ssh_key = decrypt_secret(src["ssh_key_enc"])
        except Exception as exc:
            logger.error("failed to decrypt ssh_key_enc: %s", exc)
    return token, ssh_key


def _sync_git_source(
    url: str,
    branch: str,
    local_path: str,
    token: str | None = None,
    ssh_key: str | None = None,
) -> Path:
    """Clone if needed, then pull. Used only by explicit sync operations."""
    p = _clone_git_source(url, branch, local_path, token=token, ssh_key=ssh_key)
    _pull_git_source(local_path, token=token, ssh_key=ssh_key)
    return p


def get_all_playbook_dirs(settings_value: str | None, builtin_dir: Path) -> list[Path]:
    """Return all directories to scan for playbooks, starting with builtin.

    For git sources: uses the already-cloned local cache directory WITHOUT
    pulling. Git pulls only happen via sync_all_git_sources (explicit sync button
    or after adding a new source). This keeps list_playbooks at ~0ms instead of
    blocking for 1-2s per git source on every page load.
    """
    dirs = [builtin_dir]
    if not settings_value:
        return dirs
    try:
        sources: list[dict[str, Any]] = json.loads(settings_value)
    except (json.JSONDecodeError, TypeError):
        return dirs
    for src in sources:
        src_type = src.get("type", "local")
        if src_type == "local":
            raw = src.get("path", "")
            translated = _translate_path(raw)
            p = Path(translated)
            if p.is_dir():
                dirs.append(p)
            else:
                if raw != translated:
                    logger.warning(
                        "playbook source path does not exist: %s (translated from host path: %s)",
                        p,
                        raw,
                    )
                else:
                    logger.warning("playbook source path does not exist: %s", p)
        elif src_type == "git":
            local_path = src.get("local_path") or _default_clone_path(src["url"])
            p = Path(local_path)
            if p.is_dir():
                # Already cloned — use the cached clone as-is (no pull)
                dirs.append(p)
            else:
                # First time: clone synchronously (only happens once per repo)
                try:
                    token, ssh_key = _resolve_source_credentials(src)
                    p = _clone_git_source(
                        url=src["url"],
                        branch=src.get("branch", "main"),
                        local_path=local_path,
                        token=token,
                        ssh_key=ssh_key,
                    )
                    dirs.append(p)
                except Exception as e:
                    logger.error(
                        "failed to clone git source %s: %s — run Sync to retry",
                        src.get("url"),
                        e,
                    )
    return dirs


def sync_all_git_sources(settings_value: str | None) -> list[dict[str, Any]]:
    """Sync all git sources and return per-source status dicts."""
    results: list[dict[str, Any]] = []
    if not settings_value:
        return results
    try:
        sources: list[dict[str, Any]] = json.loads(settings_value)
    except (json.JSONDecodeError, TypeError):
        return results
    for i, src in enumerate(sources):
        if src.get("type") != "git":
            continue
        url = src.get("url", "")
        branch = src.get("branch", "main")
        local_path = src.get("local_path") or _default_clone_path(url)
        try:
            token, ssh_key = _resolve_source_credentials(src)
            _sync_git_source(url=url, branch=branch, local_path=local_path, token=token, ssh_key=ssh_key)
            results.append({"index": i, "url": url, "status": "ok"})
        except Exception as e:
            results.append({"index": i, "url": url, "status": "error", "error": str(e)})
    return results
