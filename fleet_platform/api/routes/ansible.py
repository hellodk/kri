# fleet_platform/api/routes/ansible.py
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import hash_password, require_role
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.schemas.playbook import (
    AnsibleJobResponse,
    PlaybookEntryResponse,
    PlaybookRunRequest,
    PlaybookRunResponse,
)
from fleet_platform.services.playbook_discovery import discover_all
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
        await db.commit()

    task = bootstrap_node.delay(str(node.id), payload.target_ip)

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


@router.get("/playbooks", response_model=list[PlaybookEntryResponse])
async def list_playbooks(
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    entries = discover_all(_PLAYBOOKS_DIR)
    return [
        PlaybookEntryResponse(
            filename=e.filename,
            name=e.name,
            description=e.description,
            entry_type=e.entry_type,
            default_vars=e.default_vars,
        )
        for e in entries
    ]


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

    run_playbook.delay(str(job.id))

    return PlaybookRunResponse(
        job_id=job.id,
        playbook=safe_name,
        target_label=target_label,
        status="pending",
        message="Playbook queued.",
    )


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
