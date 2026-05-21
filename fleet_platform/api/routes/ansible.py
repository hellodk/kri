# fleet_platform/api/routes/ansible.py
import re
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func

_MINION_ID_RE = re.compile(r'^[a-zA-Z0-9._-]{1,128}$')
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import hash_password, require_role
from fleet_platform.services.platform_settings_svc import encrypt_secret
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.schemas.playbook import (
    AnsibleJobResponse,
    PlaybookEntryResponse,
    PlaybookRunRequest,
    PlaybookRunResponse,
    PlaybookSourceRequest,
    PlaybookSourceResponse,
    PlaybookSourceSyncResult,
    PlaybookSourcesImportRequest,
)
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.services.playbook_sources import get_all_playbook_dirs, sync_all_git_sources
from fleet_platform.workers.ansible_tasks import bootstrap_node
from fleet_platform.workers.playbook_tasks import run_playbook

router = APIRouter(prefix="/api/v1/ansible")

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent.parent / "playbooks"


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=202)
@limiter.limit("10/minute")
async def bootstrap(
    request: Request,
    payload: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if not _MINION_ID_RE.match(payload.minion_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid minion_id '{payload.minion_id}': only [a-zA-Z0-9._-] allowed",
        )

    result = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
    node = result.scalar_one_or_none()

    if node and node.bootstrap_status == "bootstrapping":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Node is already being bootstrapped",
        )

    placeholder_token = secrets.token_urlsafe(32)

    if node is None:
        node = Node(
            minion_id=payload.minion_id,
            hostname=payload.minion_id.split(".")[0],
            ip_address=payload.target_ip,
            status="unknown",
            drift_score=0,
            node_token_hash=hash_password(placeholder_token),
            first_seen_at=datetime.now(UTC),
            bootstrap_status="pending",
            bootstrap_ip=payload.target_ip,
        )
        db.add(node)
        await db.commit()
        await db.refresh(node)
    else:
        node.bootstrap_status = "pending"
        node.bootstrap_ip = payload.target_ip

    # Save SSH credentials to the node for future reuse
    if payload.ssh_username:
        node.ssh_username = payload.ssh_username
    if payload.ssh_password:
        node.ssh_password_enc = encrypt_secret(payload.ssh_password)
        node.ssh_auth_mode = "password"
    elif payload.ssh_key:
        node.ssh_key_enc = encrypt_secret(payload.ssh_key)
        node.ssh_auth_mode = "key"
    await db.commit()
    await db.refresh(node)

    task = bootstrap_node.delay(
        str(node.id),
        payload.target_ip,
        ssh_username=payload.ssh_username,
        ssh_password=payload.ssh_password,
    )

    return BootstrapResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        job_id=task.id,
        bootstrap_status="pending",
        message="Bootstrap queued. Node will appear in fleet once Salt minion connects.",
    )


@router.get("/bootstrap/{node_id}/status")
async def bootstrap_status(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "bootstrap_ip": node.bootstrap_ip,
        "bootstrap_error": node.bootstrap_error,
    }


@router.post("/bootstrap/{node_id}/cancel")
async def cancel_bootstrap(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Reset a stuck bootstrap job so the node can be re-bootstrapped."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.bootstrap_status not in ("bootstrapping", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Bootstrap status is '{node.bootstrap_status}' — nothing to cancel",
        )
    node.bootstrap_status = "failed"
    node.bootstrap_error = "Manually cancelled by user"
    await db.commit()
    return {"node_id": str(node.id), "bootstrap_status": "failed", "message": "Bootstrap cancelled"}


@router.get("/bootstrap/{node_id}/logs")
async def bootstrap_logs(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Read the Salt pillar file written before the Ansible run
    pillar_content: str | None = None
    pillar_path = Path("/srv/salt/pillar") / f"{node.minion_id}.sls"
    if pillar_path.exists():
        try:
            pillar_content = pillar_path.read_text()
        except Exception:
            pillar_content = f"(could not read {pillar_path})"
    else:
        pillar_content = f"(pillar file not found at {pillar_path})"

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "pillar_path": str(pillar_path),
        "pillar": pillar_content,
        "ansible_stdout": node.bootstrap_logs,
    }


@router.get("/bootstrap/{node_id}/history")
async def bootstrap_history(
    node_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List all bootstrap runs for a node, newest first."""
    from fleet_platform.models.bootstrap_run import BootstrapRun
    from sqlalchemy import desc

    result = await db.execute(
        select(BootstrapRun)
        .where(BootstrapRun.node_id == node_id)
        .order_by(desc(BootstrapRun.started_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    runs = result.scalars().all()

    total = await db.scalar(
        select(func.count()).select_from(
            select(BootstrapRun).where(BootstrapRun.node_id == node_id).subquery()
        )
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "target_ip": r.target_ip,
                "status": r.status,
                "error": r.error,
                "has_stdout": bool(r.ansible_stdout),
            }
            for r in runs
        ],
        "total": total or 0,
        "page": page,
        "per_page": per_page,
    }


@router.get("/bootstrap/{node_id}/history/{run_id}")
async def bootstrap_run_detail(
    node_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return full logs for a specific bootstrap run."""
    from fleet_platform.models.bootstrap_run import BootstrapRun

    result = await db.execute(
        select(BootstrapRun).where(
            BootstrapRun.id == run_id,
            BootstrapRun.node_id == node_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": str(run.id),
        "node_id": str(run.node_id),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "target_ip": run.target_ip,
        "status": run.status,
        "ansible_stdout": run.ansible_stdout,
        "error": run.error,
    }


@router.get("/playbooks", response_model=list[PlaybookEntryResponse])
async def list_playbooks(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
    all_entries = []
    for d in all_dirs:
        all_entries.extend(discover_all(d))
    return [
        PlaybookEntryResponse(
            filename=e.filename,
            name=e.name,
            description=e.description,
            entry_type=e.entry_type,
            default_vars=e.default_vars,
        )
        for e in all_entries
    ]


@router.get("/sources", response_model=list[PlaybookSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List configured extra playbook sources."""
    import json as _json
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        return []
    try:
        sources = _json.loads(setting.value)
    except (ValueError, TypeError):
        return []
    return [
        PlaybookSourceResponse(index=i, **{k: v for k, v in src.items()})
        for i, src in enumerate(sources)
    ]


@router.post("/sources", response_model=PlaybookSourceResponse, status_code=201)
async def add_source(
    payload: PlaybookSourceRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Add a new playbook source (local directory or git repository)."""
    import json as _json
    if payload.type == "local":
        if not payload.path:
            raise HTTPException(status_code=422, detail="path is required for local source")
    elif payload.type == "git":
        if not payload.url:
            raise HTTPException(status_code=422, detail="url is required for git source")

    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    sources = []
    if setting and setting.value:
        try:
            sources = _json.loads(setting.value)
        except (ValueError, TypeError):
            sources = []

    new_src: dict = {"type": payload.type}
    if payload.type == "local":
        new_src["path"] = payload.path
    elif payload.type == "git":
        new_src["url"] = payload.url
        new_src["branch"] = payload.branch
        if payload.local_path:
            new_src["local_path"] = payload.local_path
    if payload.label:
        new_src["label"] = payload.label

    sources.append(new_src)
    new_index = len(sources) - 1

    if setting:
        setting.value = _json.dumps(sources)
    else:
        setting = PlatformSetting(key="playbook_sources", value=_json.dumps(sources))
        db.add(setting)
    await db.commit()

    return PlaybookSourceResponse(index=new_index, **new_src)


@router.delete("/sources/{index}", status_code=204)
async def remove_source(
    index: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Remove a playbook source by its index."""
    import json as _json
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        raise HTTPException(status_code=404, detail="No sources configured")
    try:
        sources = _json.loads(setting.value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Corrupt sources setting")
    if index < 0 or index >= len(sources):
        raise HTTPException(status_code=404, detail=f"Source index {index} not found")
    sources.pop(index)
    setting.value = _json.dumps(sources)
    await db.commit()


@router.post("/sources/sync", response_model=PlaybookSourceSyncResult)
async def sync_sources(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Force-sync all configured git playbook sources."""
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None
    sync_results = sync_all_git_sources(sources_json)
    return PlaybookSourceSyncResult(results=sync_results)


@router.post("/sources/import", response_model=dict)
async def import_sources_csv(
    payload: PlaybookSourcesImportRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Bulk-import playbook sources from CSV text.

    Format (one entry per line):
        type, path/url, branch (for git; leave blank for local), label
    Lines starting with '#' are treated as comments and ignored.
    """
    import json as _json
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    sources: list[dict] = []
    if setting and setting.value:
        try:
            sources = _json.loads(setting.value)
        except (ValueError, TypeError):
            sources = []

    added = 0
    for raw_line in payload.csv.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        src_type = parts[0].lower()
        if src_type not in ("local", "git"):
            continue
        new_src: dict = {"type": src_type}
        if src_type == "local":
            new_src["path"] = parts[1]
        elif src_type == "git":
            new_src["url"] = parts[1]
            new_src["branch"] = parts[2] if len(parts) > 2 and parts[2] else "main"
        if len(parts) > 3 and parts[3]:
            new_src["label"] = parts[3]
        sources.append(new_src)
        added += 1

    if setting:
        setting.value = _json.dumps(sources)
    else:
        setting = PlatformSetting(key="playbook_sources", value=_json.dumps(sources))
        db.add(setting)
    if added:
        await db.commit()

    return {"added": added}


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


@router.post("/playbooks/run", response_model=PlaybookRunResponse, status_code=202)
async def run_playbook_endpoint(
    payload: PlaybookRunRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    # Use discover_all as the authoritative allowlist — only known playbooks/roles can run
    entries = discover_all(_PLAYBOOKS_DIR)
    entry = next((e for e in entries if e.filename == payload.playbook), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Playbook not found")
    safe_name = entry.filename  # trusted — came from filesystem scan, not user input

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
        extravars=payload.extravars,
        status="pending",
        triggered_by=claims["sub"],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    run_playbook.delay(
        str(job.id),
        ssh_username=payload.ssh_username,
        ssh_password=payload.ssh_password,
    )

    return PlaybookRunResponse(
        job_id=job.id,
        playbook=safe_name,
        target_label=target_label,
        status="pending",
        message="Playbook queued.",
    )


@router.post("/nodes/{node_id}/collect-grains", status_code=202)
async def collect_grains(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Trigger an Ansible run to collect grains from a live node and push to ingest."""
    from sqlalchemy import select as _sel
    result = await db.execute(_sel(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.bootstrap_ip:
        raise HTTPException(status_code=400, detail="Node has no bootstrap_ip — run bootstrap first")

    from fleet_platform.workers.celery_app import celery_app
    task = celery_app.send_task(
        "fleet_platform.workers.ansible_tasks.collect_node_grains",
        args=[str(node_id)],
        queue="maintenance",
    )
    return {"task_id": task.id, "node_id": str(node_id), "status": "queued"}


@router.get("/jobs/{job_id}", response_model=AnsibleJobResponse)
async def get_ansible_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return AnsibleJobResponse(
        id=job.id,
        playbook=job.playbook,
        target_type=job.target_type,
        target_label=job.target_label,
        extravars=job.extravars,
        status=job.status,
        triggered_by=job.triggered_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        stdout=job.stdout,
        rc=job.rc,
        created_at=job.created_at,
    )
