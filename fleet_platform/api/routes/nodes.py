# fleet_platform/api/routes/nodes.py
import asyncio
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.services.platform_settings_svc import encrypt_secret
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node, Tag
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.fleet import NodeCreateRequest, NodeDetailResponse, NodeListItem, NodeUpdateRequest
from fleet_platform.schemas.node import NodeRegisterRequest, NodeRegisterResponse
from fleet_platform.schemas.tag import TagCreate, TagResponse

router = APIRouter(prefix="/api/v1/nodes")


@router.post("/register", response_model=NodeRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_node(
    payload: NodeRegisterRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    existing = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
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
    existing = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
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

    result = await db.execute(
        select(Node).options(selectinload(Node.tags)).where(Node.id == node.id)
    )
    node = result.scalar_one()
    return NodeDetailResponse.model_validate(node)


@router.patch("/{node_id}", response_model=NodeDetailResponse)
async def update_node(
    node_id: uuid.UUID,
    payload: NodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(
        select(Node).options(selectinload(Node.tags)).where(Node.id == node_id)
    )
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

    # SSH credential updates
    if payload.ssh_username is not None:
        node.ssh_username = payload.ssh_username
    if payload.ssh_password is not None:
        node.ssh_password_enc = encrypt_secret(payload.ssh_password) if payload.ssh_password else None
    if payload.ssh_auth_mode is not None:
        node.ssh_auth_mode = payload.ssh_auth_mode
    if payload.ssh_key is not None:
        node.ssh_key_enc = encrypt_secret(payload.ssh_key) if payload.ssh_key else None

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
    await db.refresh(node)
    response = NodeDetailResponse.model_validate(node)
    # model_validate doesn't always pick up encrypted columns from ORM refresh;
    # set the flags explicitly from the in-memory node object post-commit.
    return response.model_copy(update={
        "has_ssh_password": bool(node.ssh_password_enc),
        "has_ssh_key": bool(node.ssh_key_enc),
    })


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


_SORT_FIELDS = {"drift_score", "hostname", "status", "last_seen_at", "created_at"}


@router.get("", response_model=PaginatedResponse[NodeListItem])
async def list_nodes(
    status: str | None = None,
    tag: str | None = None,
    group_id: uuid.UUID | None = None,
    search: str | None = None,
    os_version: str | None = None,
    drift_min: int | None = Query(default=None, ge=0),
    drift_max: int | None = Query(default=None, ge=0),
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

    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(Node.hostname.ilike(pattern), Node.minion_id.ilike(pattern))
        )

    if os_version:
        query = query.where(Node.os_version.ilike(f"%{os_version}%"))

    if drift_min is not None:
        query = query.where(Node.drift_score >= drift_min)

    if drift_max is not None:
        query = query.where(Node.drift_score <= drift_max)

    if tag:
        key, _, value = tag.partition(":")
        subq = (
            select(Tag.node_id)
            .where(Tag.key == key, Tag.value == value)
            .scalar_subquery()
        )
        query = query.where(Node.id.in_(subq))

    if group_id:
        from fleet_platform.models.group import GroupMember
        member_subq = (
            select(GroupMember.node_id)
            .where(GroupMember.group_id == group_id)
            .scalar_subquery()
        )
        query = query.where(Node.id.in_(member_subq))

    sort_field, _, sort_dir = sort.partition(":")
    if sort_field not in _SORT_FIELDS:
        sort_field = "drift_score"
    sort_col = getattr(Node, sort_field)
    query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    paged = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(paged)
    nodes = result.scalars().all()

    return PaginatedResponse(
        items=[NodeListItem.model_validate(n) for n in nodes],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{node_id}", response_model=NodeDetailResponse)
async def get_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(Node).options(selectinload(Node.tags)).where(Node.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return NodeDetailResponse.model_validate(node)


@router.get("/{node_id}/facts")
async def get_node_facts(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return the latest Salt grain snapshot for a node."""
    result = await db.execute(
        select(NodeFact)
        .where(NodeFact.node_id == node_id)
        .order_by(NodeFact.collected_at.desc())
        .limit(1)
    )
    fact = result.scalar_one_or_none()
    return {"grains": fact.grains if fact else {}}


@router.get("/{node_id}/packages")
async def get_node_packages(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return installed packages extracted from the latest Salt grain snapshot."""
    result = await db.execute(
        select(NodeFact)
        .where(NodeFact.node_id == node_id)
        .order_by(NodeFact.collected_at.desc())
        .limit(1)
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

    existing = await db.execute(
        select(Tag).where(Tag.node_id == node_id, Tag.key == payload.key)
    )
    tag = existing.scalar_one_or_none()
    if tag:
        if tag.source == "system":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tag '{payload.key}' is auto-populated by Salt and cannot be modified",
            )
        tag.value = payload.value
    else:
        tag = Tag(node_id=node_id, key=payload.key, value=payload.value,
                  source="user", created_at=datetime.now(UTC))
        db.add(tag)

    await audit(db, actor=claims["email"], action="node.tag.upsert",
                resource_type="node", resource_id=node_id,
                new_value={"key": payload.key, "value": payload.value})

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Concurrent insert won the race — fetch and return the existing tag
        result = await db.execute(
            select(Tag).where(Tag.node_id == node_id, Tag.key == payload.key)
        )
        tag = result.scalar_one()
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
    result = await db.execute(
        select(Tag).where(Tag.node_id == node_id, Tag.key == key)
    )
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
    await audit(db, actor=claims["email"], action="node.tag.delete",
                resource_type="node", resource_id=node_id, old_value=old_value)
    await db.commit()
