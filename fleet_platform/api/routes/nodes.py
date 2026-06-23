# fleet_platform/api/routes/nodes.py
import asyncio
import json
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.models.credential import Credential
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node, Tag
from fleet_platform.models.process_stat import NodeProcessStat
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.fleet import (
    NodeCreateRequest,
    NodeDetailResponse,
    NodeListItem,
    NodeUpdateRequest,
)
from fleet_platform.schemas.node import NodeRegisterRequest, NodeRegisterResponse
from fleet_platform.schemas.process_stat import ProcessStatOut
from fleet_platform.schemas.tag import TagCreate, TagResponse
from fleet_platform.services.platform_settings_svc import encrypt_secret
from fleet_platform.services.ssh_credential_link import owner_secret_flags, upsert_owner_ssh_credential

router = APIRouter(prefix="/api/v1/nodes")


@router.post("/register", response_model=NodeRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_node(
    payload: NodeRegisterRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    existing = await db.execute(select(Node).where(Node.minion_id == payload.minion_id))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node '{payload.minion_id}' is already registered",
        )

    token = secrets.token_urlsafe(32)
    token_hash = await asyncio.to_thread(hash_password, token)
    node = Node(
        minion_id=payload.minion_id,
        hostname=payload.hostname,
        node_token_hash=token_hash,
        first_seen_at=datetime.now(UTC),
        status="unknown",
    )
    db.add(node)

    try:
        await db.flush()
        await audit(
            db,
            actor=claims["email"],
            action="node.register",
            resource_type="node",
            resource_id=node.id,
            new_value={"minion_id": node.minion_id, "hostname": node.hostname},
        )
        await db.commit()
        await db.refresh(node)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node '{payload.minion_id}' is already registered",
        )

    return NodeRegisterResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        token=token,
    )


@router.post("", response_model=NodeDetailResponse, status_code=201)
async def create_node(
    payload: NodeCreateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    existing = await db.execute(select(Node).where(Node.minion_id == payload.minion_id))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node '{payload.minion_id}' is already registered",
        )

    token = secrets.token_urlsafe(32)
    token_hash = await asyncio.to_thread(hash_password, token)
    node = Node(
        minion_id=payload.minion_id,
        hostname=payload.hostname,
        ip_address=payload.ip_address,
        hardware_model=payload.hardware_model,
        os_version=payload.os_version,
        node_token_hash=token_hash,
        first_seen_at=datetime.now(UTC),
        status="unknown",
    )
    db.add(node)

    try:
        await db.flush()
        await audit(
            db,
            actor=claims["email"],
            action="node.create",
            resource_type="node",
            resource_id=node.id,
            new_value={"minion_id": node.minion_id, "hostname": node.hostname},
        )
        await db.commit()
        await db.refresh(node)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node '{payload.minion_id}' is already registered",
        )

    result = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node.id))
    node = result.scalar_one()
    return NodeDetailResponse.model_validate(node)


@router.patch("/{node_id}", response_model=NodeDetailResponse)
async def update_node(
    node_id: uuid.UUID,
    payload: NodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    old_value: dict = {}
    if payload.hostname is not None:
        old_value["hostname"] = node.hostname
        node.hostname = payload.hostname
    if payload.ip_address is not None:
        old_value["ip_address"] = str(node.ip_address) if node.ip_address else None
        node.ip_address = payload.ip_address
    if payload.hardware_model is not None:
        old_value["hardware_model"] = node.hardware_model
        node.hardware_model = payload.hardware_model
    if payload.os_version is not None:
        old_value["os_version"] = node.os_version
        node.os_version = payload.os_version

    # SSH credentials (#725). An explicit credential_id attaches an existing
    # Credential by FK; otherwise inline ssh_* input is upserted into the node's
    # dedicated Credential row (never the deprecated inline columns).
    if payload.credential_id is not None:
        cred = await db.get(Credential, payload.credential_id)
        if cred is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
        node.credential_id = payload.credential_id
    else:
        cred_id = await upsert_owner_ssh_credential(
            db,
            owner_name=f"node:{node.minion_id}",
            current_credential_id=node.credential_id,
            ssh_username=payload.ssh_username,
            ssh_password=payload.ssh_password,
            ssh_key=payload.ssh_key,
            ssh_auth_mode=payload.ssh_auth_mode,
        )
        if cred_id is not None:
            node.credential_id = cred_id
    # VNC credential update
    if payload.vnc_password is not None:
        node.vnc_password_enc = encrypt_secret(payload.vnc_password) if payload.vnc_password else None

    await audit(
        db,
        actor=claims["email"],
        action="node.update",
        resource_type="node",
        resource_id=node_id,
        old_value=old_value,
        new_value=payload.model_dump(exclude_none=True),
    )
    await db.commit()
    # Re-query after commit so all columns (including encrypted ones) are fresh
    result2 = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node_id))
    node = result2.scalar_one()
    has_password, has_key = await owner_secret_flags(
        db,
        credential_id=node.credential_id,
        inline_password_enc=node.ssh_password_enc,
        inline_key_enc=node.ssh_key_enc,
    )
    return NodeDetailResponse.model_validate(node).model_copy(
        update={
            "has_ssh_password": has_password,
            "has_ssh_key": has_key,
            "has_vnc_password": bool(node.vnc_password_enc),
        }
    )


@router.delete("/{node_id}", status_code=204)
async def delete_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    old_value = {"minion_id": node.minion_id, "hostname": node.hostname}
    await audit(
        db,
        actor=claims["email"],
        action="node.delete",
        resource_type="node",
        resource_id=node_id,
        old_value=old_value,
    )
    await db.delete(node)
    await db.commit()


_SORT_FIELDS = {"drift_score", "hostname", "status", "last_seen_at", "created_at", "cpu_usage_pct", "mem_usage_pct"}


@router.get("", response_model=PaginatedResponse[NodeListItem])
async def list_nodes(
    status: str | None = None,
    health: str | None = None,
    tag: str | None = None,
    group_id: uuid.UUID | None = None,
    search: str | None = None,
    os_version: str | None = None,
    drift_min: int | None = Query(default=None, ge=0),
    drift_max: int | None = Query(default=None, ge=0),
    cpu_min: float | None = Query(default=None),
    mem_min: float | None = Query(default=None),
    sort: str = "drift_score:desc",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    from sqlalchemy import or_

    query = select(Node).options(selectinload(Node.tags))

    if status:
        query = query.where(Node.status == status)

    if health:
        from fleet_platform.services.node_health import health_case

        query = query.where(health_case(Node) == health)

    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Node.hostname.ilike(pattern), Node.minion_id.ilike(pattern)))

    if os_version:
        query = query.where(Node.os_version.ilike(f"%{os_version}%"))

    if drift_min is not None:
        query = query.where(Node.drift_score >= drift_min)

    if drift_max is not None:
        query = query.where(Node.drift_score <= drift_max)

    if cpu_min is not None:
        query = query.where(Node.cpu_usage_pct >= cpu_min)

    if mem_min is not None:
        query = query.where(Node.mem_usage_pct >= mem_min)

    if tag:
        key, _sep1, value = tag.partition(":")
        subq = select(Tag.node_id).where(Tag.key == key, Tag.value == value).scalar_subquery()
        query = query.where(Node.id.in_(subq))

    if group_id:
        from fleet_platform.models.group import GroupMember

        member_subq = select(GroupMember.node_id).where(GroupMember.group_id == group_id).scalar_subquery()
        query = query.where(Node.id.in_(member_subq))

    sort_field, _sep2, sort_dir = sort.partition(":")
    if sort_field == "health":
        from fleet_platform.services.node_health import health_sort_rank

        sort_col = health_sort_rank(Node)
    else:
        if sort_field not in _SORT_FIELDS:
            sort_field = "drift_score"
        sort_col = getattr(Node, sort_field)
    query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    paged = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(paged)
    nodes = result.scalars().all()

    # Build group_count per node in one aggregate query
    if nodes:
        from fleet_platform.models.group import GroupMember as _GM

        node_ids = [n.id for n in nodes]
        gc_result = await db.execute(
            select(_GM.node_id, func.count(_GM.group_id).label("cnt"))
            .where(_GM.node_id.in_(node_ids))
            .group_by(_GM.node_id)
        )
        group_count_map = {row.node_id: row.cnt for row in gc_result}
    else:
        group_count_map = {}

    items = []
    for n in nodes:
        item = NodeListItem.model_validate(n)
        item.group_count = group_count_map.get(n.id, 0)
        items.append(item)

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{node_id}", response_model=NodeDetailResponse)
async def get_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    has_password, has_key = await owner_secret_flags(
        db,
        credential_id=node.credential_id,
        inline_password_enc=node.ssh_password_enc,
        inline_key_enc=node.ssh_key_enc,
    )
    return NodeDetailResponse.model_validate(node).model_copy(
        update={"has_ssh_password": has_password, "has_ssh_key": has_key}
    )


class SshTestResponse(BaseModel):
    node_id: str
    ssh_state: str  # ok | auth_failed | unreachable | unknown
    ssh_checked_at: datetime | None = None
    ssh_detail: str | None = None


@router.post("/ssh-refresh")
async def refresh_all_ssh(
    _: dict = Depends(require_role("operator", "admin")),
):
    """Queue an immediate SSH reachability sweep for the whole fleet (#356-ui).

    Reuses the same Celery task as the 15-minute beat schedule; results land on
    each node's ``ssh_state`` and the dashboard picks them up on its next poll.
    """
    # Lazy import: keep Celery/worker imports out of the API module load path.
    from fleet_platform.workers.connectivity_tasks import check_ssh_connectivity

    task = check_ssh_connectivity.delay()
    return {"status": "queued", "task_id": getattr(task, "id", None)}


@router.post("/{node_id}/ssh-test", response_model=SshTestResponse)
async def test_node_ssh(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Run an on-demand SSH probe for one node and persist the fresh result.

    Resolves the node's effective credential, probes TCP :22 + auth off the event
    loop, and stores the four-state outcome. Mirrors the periodic sweep so the
    cached badge and this button agree.
    """
    from fleet_platform.services.credential_resolver import resolve_node_credentials
    from fleet_platform.services.ssh_probe import probe_node_ssh

    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    creds = await resolve_node_credentials(node, db)
    probe = await asyncio.to_thread(probe_node_ssh, node, creds)

    node.ssh_state = probe["state"]
    node.ssh_detail = probe.get("detail")
    node.ssh_checked_at = datetime.now(UTC)
    await db.commit()

    return SshTestResponse(
        node_id=str(node_id),
        ssh_state=node.ssh_state,
        ssh_checked_at=node.ssh_checked_at,
        ssh_detail=node.ssh_detail,
    )


@router.get("/{node_id}/credential")
async def get_node_resolved_credential(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Resolved SSH credential source for a node + multi-group conflict info (#702).

    Never returns secrets. Surfaces which credential a node will actually use and
    warns when 2+ member groups carry credentials so the winner is explicit.
    """
    from fleet_platform.models.group import Group, GroupMember
    from fleet_platform.services.credential_resolver import has_usable_secret, resolve_node_credentials

    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    creds = await resolve_node_credentials(node, db)

    # Member groups that carry a credential (FK or inline), in resolution order.
    cred_groups = (
        (
            await db.execute(
                select(Group)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.node_id == node_id)
                .where((Group.credential_id.isnot(None)) | (Group.ssh_username.isnot(None)))
                .order_by(Group.credential_priority.desc(), Group.name.asc())
            )
        )
        .scalars()
        .all()
    )
    conflict_groups = [{"name": g.name, "credential_priority": g.credential_priority} for g in cred_groups]

    return {
        "node_id": str(node_id),
        "credential_source": creds["credential_source"],
        "ssh_user": creds["ssh_user"],
        "auth_mode": creds["auth_mode"],
        "has_usable_secret": has_usable_secret(creds),
        "node_credential_id": str(node.credential_id) if node.credential_id else None,
        "multi_group_conflict": len(cred_groups) >= 2 and creds["credential_source"].startswith("group:"),
        "credential_bearing_groups": conflict_groups,
    }


@router.get("/{node_id}/facts")
async def get_node_facts(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return the latest Salt grain snapshot for a node."""
    result = await db.execute(
        select(NodeFact).where(NodeFact.node_id == node_id).order_by(NodeFact.collected_at.desc()).limit(1)
    )
    fact = result.scalar_one_or_none()
    return {"grains": fact.grains if fact else {}}


@router.get("/{node_id}/packages")
async def get_node_packages(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return installed packages extracted from the latest Salt grain snapshot."""
    result = await db.execute(
        select(NodeFact).where(NodeFact.node_id == node_id).order_by(NodeFact.collected_at.desc()).limit(1)
    )
    fact = result.scalar_one_or_none()
    if not fact:
        return {"items": [], "source": "grains"}

    grains = fact.grains
    pkgs_raw = grains.get("pkgs") or grains.get("brew_pkgs") or {}
    packages = [
        {"name": name, "version": version, "source": "brew"}
        for name, version in (pkgs_raw.items() if isinstance(pkgs_raw, dict) else [])
    ]
    return {"items": packages, "source": "grains", "collected_at": fact.collected_at}


@router.get("/{node_id}/process_stats")
async def get_node_process_stats(
    node_id: uuid.UUID,
    sort: str = Query("mem_rss_bytes", pattern="^(mem_rss_bytes|cpu_pct)$"),
    limit: int = Query(100, ge=1, le=250),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return the latest per-process snapshot for a node, sorted by pressure."""
    node = (await db.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    latest = (
        await db.execute(select(func.max(NodeProcessStat.collected_at)).where(NodeProcessStat.node_id == node_id))
    ).scalar_one_or_none()

    if latest is None:
        return {"node_id": str(node_id), "collected_at": None, "count": 0, "processes": []}

    sort_col = {"mem_rss_bytes": NodeProcessStat.mem_rss_bytes, "cpu_pct": NodeProcessStat.cpu_pct}[sort]
    rows = (
        (
            await db.execute(
                select(NodeProcessStat)
                .where(NodeProcessStat.node_id == node_id, NodeProcessStat.collected_at == latest)
                .order_by(sort_col.desc().nullslast())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return {
        "node_id": str(node_id),
        "collected_at": latest,
        "count": len(rows),
        "processes": [ProcessStatOut.model_validate(r) for r in rows],
    }


@router.post("/{node_id}/tags", response_model=TagResponse, status_code=201)
async def add_node_tag(
    node_id: uuid.UUID,
    payload: TagCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    existing = await db.execute(select(Tag).where(Tag.node_id == node_id, Tag.key == payload.key))
    tag = existing.scalar_one_or_none()
    if tag:
        if tag.source == "system":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tag '{payload.key}' is auto-populated by Salt and cannot be modified",
            )
        tag.value = payload.value
    else:
        tag = Tag(node_id=node_id, key=payload.key, value=payload.value, source="user", created_at=datetime.now(UTC))
        db.add(tag)

    await audit(
        db,
        actor=claims["email"],
        action="node.tag.upsert",
        resource_type="node",
        resource_id=node_id,
        new_value={"key": payload.key, "value": payload.value},
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Concurrent insert won the race — fetch and return the existing tag
        tag_result = await db.execute(select(Tag).where(Tag.node_id == node_id, Tag.key == payload.key))
        tag = tag_result.scalar_one()
        return TagResponse.model_validate(tag)

    await db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.delete("/{node_id}/tags/{key}", status_code=204)
async def delete_node_tag(
    node_id: uuid.UUID,
    key: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Tag).where(Tag.node_id == node_id, Tag.key == key))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    if tag.source == "system":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tag '{key}' is auto-populated by Salt and cannot be deleted",
        )

    old_value = {"key": tag.key, "value": tag.value}
    await db.delete(tag)
    await audit(
        db,
        actor=claims["email"],
        action="node.tag.delete",
        resource_type="node",
        resource_id=node_id,
        old_value=old_value,
    )
    await db.commit()


class MaintenanceModeRequest(BaseModel):
    enabled: bool


@router.patch("/{node_id}/maintenance", response_model=NodeDetailResponse)
async def set_maintenance_mode(
    node_id: uuid.UUID,
    payload: MaintenanceModeRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    old_value = {"maintenance_mode": node.maintenance_mode}
    node.maintenance_mode = payload.enabled

    await audit(
        db,
        actor=claims["email"],
        action="node.maintenance.set",
        resource_type="node",
        resource_id=node_id,
        old_value=old_value,
        new_value={"maintenance_mode": payload.enabled},
    )
    await db.commit()
    result2 = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node_id))
    node = result2.scalar_one()
    return NodeDetailResponse.model_validate(node)


def _parse_tart_output(output: str) -> list[dict]:
    """Parse tart list output (JSON or plain text fallback)."""
    if not output or "tart_not_found" in output or "not found" in output.lower():
        return []

    # Try JSON first (tart list --format=json)
    try:
        data = json.loads(output)
        if isinstance(data, list):
            return [
                {
                    "name": vm.get("name", ""),
                    "state": vm.get("state", "unknown"),
                    "cpu": vm.get("cpu", None),
                    "memory": vm.get("memory", None),
                    "source": vm.get("source", ""),
                }
                for vm in data
            ]
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: plain text tart list output
    # Format: Name    Source    State
    vms = []
    for line in output.strip().splitlines():
        if line.startswith("Name") or not line.strip():
            continue
        parts = line.split()
        if parts:
            vms.append(
                {
                    "name": parts[0] if len(parts) > 0 else "",
                    "state": parts[2] if len(parts) > 2 else "unknown",
                    "cpu": None,
                    "memory": None,
                    "source": parts[1] if len(parts) > 1 else "",
                }
            )
    return vms


class NodeVMsResponse(BaseModel):
    node_id: str
    minion_id: str | None
    vms: list[dict]
    error: str | None = None


@router.get("/{node_id}/vms", response_model=NodeVMsResponse)
async def list_node_vms(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
) -> NodeVMsResponse:
    """List tart VMs on a node by running 'tart list' via Salt cmd.run."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    minion_id = node.minion_id
    if not minion_id:
        return NodeVMsResponse(node_id=str(node_id), minion_id=None, vms=[], error="Node has no minion_id")

    # Run tart list via Salt cmd.run
    from fleet_platform.workers.salt_tasks import run_salt_cmd as salt_run_cmd

    try:
        result_dict = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: salt_run_cmd.delay(
                function="cmd.run",
                target_minions=[minion_id],
                args=["tart list --format=json 2>/dev/null || tart list 2>/dev/null || echo 'tart_not_found'"],
            ).get(timeout=15),
        )
    except Exception as e:
        return NodeVMsResponse(
            node_id=str(node_id), minion_id=minion_id, vms=[], error=f"Failed to fetch VMs: {str(e)[:200]}"
        )

    raw_output = ""
    if isinstance(result_dict, dict) and "result" in result_dict:
        ret = result_dict["result"]
        if isinstance(ret, list) and ret:
            raw_output = ret[0].get(minion_id, "") or ""

    vms = _parse_tart_output(raw_output)
    return NodeVMsResponse(node_id=str(node_id), minion_id=minion_id, vms=vms)
