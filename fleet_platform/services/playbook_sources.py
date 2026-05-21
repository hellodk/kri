"""Manage external playbook sources (extra dirs + git repos)."""
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _sync_git_source(url: str, branch: str, local_path: str) -> Path:
    """Clone or pull a git repo. Returns the local path."""
    p = Path(local_path)
    if p.exists():
        subprocess.run(
            ["git", "-C", str(p), "pull", "--ff-only"],
            check=False,
            capture_output=True,
            timeout=30,
        )
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", branch, url, str(p)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    return p


def get_all_playbook_dirs(settings_value: str | None, builtin_dir: Path) -> list[Path]:
    """Return all directories to scan for playbooks, starting with builtin."""
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
            p = Path(src.get("path", ""))
            if p.is_dir():
                dirs.append(p)
            else:
                logger.warning("playbook source path does not exist: %s", p)
        elif src_type == "git":
            try:
                p = _sync_git_source(
                    url=src["url"],
                    branch=src.get("branch", "main"),
                    local_path=src.get(
                        "local_path",
                        f"/tmp/kri-git/{src['url'].split('/')[-1].replace('.git', '')}",
                    ),
                )
                dirs.append(p)
            except Exception as e:
                logger.error("failed to sync git source %s: %s", src.get("url"), e)
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
        local_path = src.get(
            "local_path",
            f"/tmp/kri-git/{url.split('/')[-1].replace('.git', '')}",
        )
        try:
            _sync_git_source(url=url, branch=branch, local_path=local_path)
            results.append({"index": i, "url": url, "status": "ok"})
        except Exception as e:
            results.append({"index": i, "url": url, "status": "error", "error": str(e)})
    return results
