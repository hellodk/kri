# fleet_platform/api/routes/nodes.py
import asyncio
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node, Tag
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.fleet import NodeDetailResponse, NodeListItem
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


_SORT_FIELDS = {"drift_score", "hostname", "status", "last_seen_at", "created_at"}


@router.get("", response_model=PaginatedResponse[NodeListItem])
async def list_nodes(
    status: str | None = None,
    tag: str | None = None,
    group_id: uuid.UUID | None = None,
    sort: str = "drift_score:desc",
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(Node).options(selectinload(Node.tags))

    if status:
        query = query.where(Node.status == status)

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
        tag.value = payload.value
    else:
        tag = Tag(node_id=node_id, key=payload.key, value=payload.value,
                  created_at=datetime.now(UTC))
        db.add(tag)

    await audit(db, actor=claims["email"], action="node.tag.upsert",
                resource_type="node", resource_id=node_id,
                new_value={"key": payload.key, "value": payload.value})
    await db.commit()
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

    old_value = {"key": tag.key, "value": tag.value}
    await db.delete(tag)
    await audit(db, actor=claims["email"], action="node.tag.delete",
                resource_type="node", resource_id=node_id, old_value=old_value)
    await db.commit()
