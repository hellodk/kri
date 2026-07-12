# fleet_platform/api/routes/ansible/playbooks.py
"""Playbook routes: /playbooks/..."""

import asyncio
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.schemas.playbook import (
    PlaybookEntryResponse,
    PlaybookRunRequest,
    PlaybookRunResponse,
)
from fleet_platform.services.extravars import _scrub_extravars
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.services.playbook_sources import get_all_playbook_dirs
from fleet_platform.workers.celery_app import celery_app

from ._router import _BOOTSTRAP_ONLY_PLAYBOOKS, _PLAYBOOKS_DIR, router


@router.get("/playbooks", response_model=list[PlaybookEntryResponse])
async def list_playbooks(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("viewer", "operator", "admin")),
):
    import json as _json
    import uuid as _uuid

    from fleet_platform.services.playbook_catalog_svc import get_enabled

    # Fix #460: guard against missing sub claim
    _sub = claims.get("sub")
    if not _sub:
        raise HTTPException(status_code=401, detail="Missing user identity in token")
    user_id = _uuid.UUID(_sub)

    # Load sources_json early so it's available for legacy fallback below
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    sources: list[dict] = []
    if sources_json:
        try:
            sources = _json.loads(sources_json)
        except (ValueError, TypeError):
            sources = []

    enabled = await get_enabled(db, user_id=user_id)
    if not enabled:
        # Fix #447/#503: legacy fallback when no enabled entries exist — covers
        # both "catalog never configured" (catalog_total == 0) and "catalog has
        # rows but all disabled" (catalog_total > 0, enabled empty).
        # Previously guarded by catalog_total == 0 which silently returned []
        # when all entries were disabled — fixed by always falling back here.
        all_dirs_legacy = await asyncio.to_thread(get_all_playbook_dirs, sources_json, _PLAYBOOKS_DIR)
        legacy_entries = []
        for d in all_dirs_legacy:
            for e in discover_all(d):
                legacy_entries.append(
                    PlaybookEntryResponse(
                        filename=e.filename,
                        name=e.name,
                        description=e.description,
                        entry_type=e.entry_type,
                        default_vars=e.default_vars,
                        lint_errors=e.lint_errors,
                        source_dir=str(d),
                        catalog_id=None,
                        is_favorite=False,
                    )
                )
        return legacy_entries

    # Fix #496: build a per-source identity map (source_key → dir) so that absent
    # source dirs do not corrupt the positional mapping between sources and dirs.
    # get_all_playbook_dirs skips absent dirs, making it shorter than sources[];
    # using positional index (i - 1) into sources[] was therefore wrong.
    from fleet_platform.services.playbook_sources import (
        _default_clone_path,
        _translate_path,
    )

    # Build source_key → resolved_dir for each configured source (mirroring
    # get_all_playbook_dirs logic) but keyed by identity, not position.
    source_dir_map: dict[str, Path] = {}
    for src in sources:
        src_type = src.get("type", "local")
        source_key = src.get("url") or src.get("path") or ""
        if not source_key:
            continue
        if src_type == "local":
            raw = src.get("path", "")
            translated = _translate_path(raw)
            p = Path(translated)
            if p.is_dir():
                source_dir_map[source_key] = p
        elif src_type == "git":
            url = src.get("url", "")
            if not url:
                continue
            local_path = src.get("local_path") or _default_clone_path(url)
            p = Path(local_path)
            if p.is_dir():
                source_dir_map[source_key] = p

    catalog_lookup: dict[tuple[str, str], dict] = {(e["source_key"], e["filename"]): e for e in enabled}

    all_entries: list[PlaybookEntryResponse] = []

    # Built-in dir (always index 0 in get_all_playbook_dirs)
    builtin_key = str(_PLAYBOOKS_DIR)
    for e in discover_all(_PLAYBOOKS_DIR):
        info = catalog_lookup.get((builtin_key, e.filename))
        if info is None:
            continue
        all_entries.append(
            PlaybookEntryResponse(
                filename=e.filename,
                name=e.name,
                description=e.description,
                entry_type=e.entry_type,
                default_vars=e.default_vars,
                lint_errors=e.lint_errors,
                source_dir=builtin_key,
                catalog_id=info["catalog_id"],
                is_favorite=info["is_favorite"],
            )
        )

    # Per-source dirs — keyed by identity, not position
    for source_key, d in source_dir_map.items():
        for e in discover_all(d):
            info = catalog_lookup.get((source_key, e.filename))
            if info is None:
                continue
            all_entries.append(
                PlaybookEntryResponse(
                    filename=e.filename,
                    name=e.name,
                    description=e.description,
                    entry_type=e.entry_type,
                    default_vars=e.default_vars,
                    lint_errors=e.lint_errors,
                    source_dir=str(d),
                    catalog_id=info["catalog_id"],
                    is_favorite=info["is_favorite"],
                )
            )
    return all_entries


@router.get("/playbooks/content")
async def get_playbook_content(
    filename: str,
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return raw YAML content of a discovered playbook or role's main task file."""
    entries = discover_all(_PLAYBOOKS_DIR)
    entry = next((e for e in entries if e.filename == filename), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Playbook not found")

    if entry.entry_type == "playbook":
        content_path = _PLAYBOOKS_DIR / filename
    else:
        # For roles: show tasks/main.yml
        role_name = filename.replace("roles/", "")
        content_path = _PLAYBOOKS_DIR / "roles" / role_name / "tasks" / "main.yml"

    if not content_path.exists():
        raise HTTPException(status_code=404, detail="Playbook file not found on disk")

    try:
        content = content_path.read_text()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read playbook: {e}")

    return {"filename": filename, "content": content}


@router.get("/playbooks/tree")
async def get_playbook_tree(
    filename: str = Query(..., description="Playbook filename or role name"),
    source_dir: str | None = Query(None, description="Absolute source directory path"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return the dependency tree of a playbook/role in execution order."""
    import yaml as _yaml

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    # Find which directory contains this filename
    if source_dir:
        playbooks_dir = Path(source_dir)
    else:
        all_dirs = await asyncio.to_thread(get_all_playbook_dirs, sources_json, _PLAYBOOKS_DIR)
        playbooks_dir = next(
            (d for d in all_dirs if (d / filename).exists() or (d / "roles" / filename.replace("roles/", "")).is_dir()),
            _PLAYBOOKS_DIR,
        )

    # Determine if this is a playbook file or a role directory
    playbook_path = playbooks_dir / filename
    roles_dir = playbooks_dir / "roles"

    def _file_node(rel_path: str, label: str, node_type: str, task_name: str | None = None) -> dict:
        abs_path = playbooks_dir / rel_path
        return {
            "type": node_type,
            "path": rel_path,
            "label": label,
            "exists": abs_path.exists(),
            "task_name": task_name,
        }

    def _walk_role(role_name: str) -> dict | None:
        role_path = roles_dir / role_name
        if not role_path.is_dir():
            return None

        children = []
        # Standard Ansible role directory order
        for subdir, node_type, label_prefix in [
            ("tasks", "tasks", "tasks/"),
            ("handlers", "handlers", "handlers/"),
            ("defaults", "defaults", "defaults/"),
            ("vars", "vars", "vars/"),
            ("templates", "template", "templates/"),
            ("files", "file", "files/"),
            ("meta", "meta", "meta/"),
        ]:
            subpath = role_path / subdir
            if subpath.is_dir():
                for f in sorted(subpath.iterdir()):
                    if f.is_file() and not f.name.startswith("."):
                        rel = str(f.relative_to(playbooks_dir))
                        children.append(_file_node(rel, f"{label_prefix}{f.name}", node_type))

        return {
            "type": "role",
            "path": f"roles/{role_name}",
            "label": role_name,
            "exists": True,
            "children": children,
        }

    def _extract_templates_from_tasks(tasks: list) -> list[dict]:
        """Find template: tasks and return the .j2 file references."""
        nodes = []
        if not isinstance(tasks, list):
            return nodes
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_name = task.get("name", "")
            # template module
            for key in ("template", "ansible.builtin.template"):
                tmpl = task.get(key)
                if isinstance(tmpl, dict):
                    src = tmpl.get("src", "")
                    if src:
                        # src is relative to role's templates/ or playbook's templates/
                        for candidate in [f"templates/{src}", src]:
                            if (playbooks_dir / candidate).exists():
                                nodes.append(_file_node(candidate, src, "template", task_name))
                                break
                        else:
                            nodes.append(_file_node(f"templates/{src}", src, "template", task_name))
            # include_tasks / import_tasks
            _task_include_keys = (
                "include_tasks",
                "import_tasks",
                "ansible.builtin.include_tasks",
                "ansible.builtin.import_tasks",
            )
            for key in _task_include_keys:
                inc = task.get(key)
                if isinstance(inc, str):
                    nodes.append(_file_node(inc, inc, "include", task_name))
                elif isinstance(inc, dict) and "file" in inc:
                    f = inc["file"]
                    nodes.append(_file_node(f, f, "include", task_name))
        return nodes

    nodes: list[dict] = []

    if playbook_path.exists() and playbook_path.is_file():
        # It's a playbook .yml file
        nodes.append(_file_node(filename, filename, "playbook"))

        try:
            with open(playbook_path) as f:
                plays = _yaml.safe_load(f) or []
        except Exception:
            plays = []

        seen_paths: set[str] = {filename}

        for play in plays if isinstance(plays, list) else []:
            if not isinstance(play, dict):
                continue

            # vars_files
            for vf in play.get("vars_files", []):
                if isinstance(vf, str) and vf not in seen_paths:
                    seen_paths.add(vf)
                    nodes.append(_file_node(vf, vf, "vars"))

            # roles
            for role in play.get("roles", []):
                role_name = role if isinstance(role, str) else role.get("role", role.get("name", ""))
                if role_name:
                    role_node = _walk_role(role_name)
                    if role_node:
                        nodes.append(role_node)

            # tasks (top-level)
            task_nodes = _extract_templates_from_tasks(play.get("tasks", []))
            for tn in task_nodes:
                if tn["path"] not in seen_paths:
                    seen_paths.add(tn["path"])
                    nodes.append(tn)

            # handlers
            for handler in play.get("handlers", []):
                pass  # inline handlers don't have separate files unless notify

    elif filename and not filename.endswith(".yml"):
        # Treat as a role name
        role_node = _walk_role(filename)
        if role_node:
            nodes.append(role_node)
        else:
            raise HTTPException(status_code=404, detail=f"Playbook or role '{filename}' not found")
    else:
        raise HTTPException(status_code=404, detail=f"Playbook '{filename}' not found")

    return {"filename": filename, "nodes": nodes}


@router.post("/playbooks/run", response_model=PlaybookRunResponse, status_code=202)
async def run_playbook_endpoint(
    payload: PlaybookRunRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    # Use discover_all across ALL configured sources — only known playbooks/roles can run.
    # Previously only checked the builtin _PLAYBOOKS_DIR, causing external-source playbooks
    # to always 404 (#580).  Now uses the same resolver as the worker.

    _sources_setting = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    _sources_row = _sources_setting.scalar_one_or_none()
    _sources_json = _sources_row.value if _sources_row else None
    _all_dirs = await asyncio.to_thread(get_all_playbook_dirs, _sources_json, _PLAYBOOKS_DIR)
    entry = None
    for _dir in _all_dirs:
        _found = next((e for e in discover_all(_dir) if e.filename == payload.playbook), None)
        if _found:
            entry = _found
            break
    if not entry:
        raise HTTPException(status_code=404, detail="Playbook not found")
    safe_name = entry.filename  # trusted — came from filesystem scan, not user input

    if safe_name in _BOOTSTRAP_ONLY_PLAYBOOKS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bootstrap playbooks must be run via the dedicated bootstrap endpoint",
        )

    target_label = payload.target_id
    if payload.target_type == "node":
        node_result = await db.execute(select(Node).where(Node.id == uuid.UUID(payload.target_id)))
        node = node_result.scalar_one_or_none()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        target_label = node.hostname or node.minion_id
    elif payload.target_type == "group":
        from fleet_platform.models.group import Group

        grp_result = await db.execute(select(Group).where(Group.id == uuid.UUID(payload.target_id)))
        grp = grp_result.scalar_one_or_none()
        if not grp:
            raise HTTPException(status_code=404, detail="Group not found")
        target_label = grp.name

    job = AnsibleJob(
        playbook=safe_name,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_label=target_label,
        extravars=_scrub_extravars(payload.extravars) if payload.extravars else payload.extravars,
        verbosity=max(0, min(4, payload.verbosity or 0)),
        timeout_seconds=max(60, min(21600, payload.timeout_seconds)),
        status="pending",
        triggered_by=claims["sub"],
    )
    db.add(job)
    await db.flush()
    await audit(
        db,
        actor=claims["email"],
        action="playbook.run",
        resource_type="ansible_job",
        resource_id=job.id,
        new_value={"playbook": safe_name, "target_type": payload.target_type, "target_id": payload.target_id},
    )
    await db.commit()
    await db.refresh(job)

    task = celery_app.send_task(
        "fleet_platform.workers.playbook_tasks.run_playbook",
        args=[str(job.id)],
        kwargs={"ssh_username": payload.ssh_username, "verbosity": job.verbosity},
        queue="ansible",
    )
    job.celery_task_id = task.id
    await db.commit()

    return PlaybookRunResponse(
        job_id=job.id,
        playbook=safe_name,
        target_label=target_label,
        status="pending",
        message="Playbook queued.",
    )


@router.get("/playbooks/{playbook_name:path}/stats")
async def playbook_stats(
    playbook_name: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
) -> dict:
    """Return duration statistics for the last 5 completed runs of a playbook."""
    rows = await db.execute(
        select(AnsibleJob)
        .where(
            AnsibleJob.playbook == playbook_name,
            AnsibleJob.status == "completed",
            AnsibleJob.started_at.is_not(None),
            AnsibleJob.completed_at.is_not(None),
        )
        .order_by(AnsibleJob.completed_at.desc())
        .limit(5)
    )
    jobs = rows.scalars().all()

    durations = []
    for j in jobs:
        if j.started_at and j.completed_at:
            secs = (j.completed_at - j.started_at).total_seconds()
            if secs > 0:
                durations.append(int(secs))

    if not durations:
        return {"playbook": playbook_name, "run_count": 0, "last_duration_seconds": None, "avg_duration_seconds": None}

    return {
        "playbook": playbook_name,
        "run_count": len(durations),
        "last_duration_seconds": durations[0],
        "avg_duration_seconds": int(sum(durations) / len(durations)),
    }
