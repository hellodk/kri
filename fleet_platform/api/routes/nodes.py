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
from fleet_platform.models.node import Node, Tag
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.fleet import NodeDetailResponse, NodeListItem
from fleet_platform.schemas.node import NodeRegisterRequest, NodeRegisterResponse

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
