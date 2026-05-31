"""Manage external playbook sources (extra dirs + git repos)."""
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

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
        container_prefix = entry[colon_idx + 1:]
        if host_path.startswith(host_prefix):
            translated = container_prefix + host_path[len(host_prefix):]
            logger.debug(
                "playbook path translated: %s → %s (map entry: %s:%s)",
                host_path, translated, host_prefix, container_prefix,
            )
            return translated

    return host_path


def _default_clone_path(url: str) -> str:
    repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    return str(_GIT_CACHE_DIR / repo_name)


def _clone_git_source(url: str, branch: str, local_path: str) -> Path:
    """Clone a git repo for the first time. Does NOT pull — use _pull_git_source for updates."""
    p = Path(local_path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", branch, url, str(p)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    return p


def _pull_git_source(local_path: str) -> None:
    """Pull latest changes into an already-cloned repo."""
    subprocess.run(
        ["git", "-C", local_path, "pull", "--ff-only"],
        check=False,
        capture_output=True,
        timeout=30,
    )


def _sync_git_source(url: str, branch: str, local_path: str) -> Path:
    """Clone if needed, then pull. Used only by explicit sync operations."""
    p = _clone_git_source(url, branch, local_path)
    _pull_git_source(local_path)
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
                        p, raw,
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
                    p = _clone_git_source(
                        url=src["url"],
                        branch=src.get("branch", "main"),
                        local_path=local_path,
                    )
                    dirs.append(p)
                except Exception as e:
                    logger.error(
                        "failed to clone git source %s: %s — run Sync to retry",
                        src.get("url"), e,
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
            _sync_git_source(url=url, branch=branch, local_path=local_path)
            results.append({"index": i, "url": url, "status": "ok"})
        except Exception as e:
            results.append({"index": i, "url": url, "status": "error", "error": str(e)})
    return results
