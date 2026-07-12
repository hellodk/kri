# fleet_platform/api/routes/groups.py
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.credential import Credential
from fleet_platform.models.group import Group, GroupMember
from fleet_platform.models.node import Node
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.fleet import NodeListItem
from fleet_platform.schemas.group import GroupCreate, GroupMemberAdd, GroupResponse, GroupUpdate
from fleet_platform.services.credential_group_svc import get_group_credential_id, set_group_credential
from fleet_platform.services.group_resolver import resolve_dynamic_group, validate_predicate
from fleet_platform.services.ssh_credential_link import owner_secret_flags, upsert_owner_ssh_credential

router = APIRouter(prefix="/api/v1/groups")


async def _get_group_or_404(group_id: uuid.UUID, db: AsyncSession) -> Group:
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


async def _member_count(group_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).where(GroupMember.group_id == group_id))
    return result.scalar_one() or 0


def _to_response(group: Group, count: int) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        type=group.type,
        predicate=group.predicate,
        member_count=count,
        created_at=group.created_at,
    )


@router.get("", response_model=PaginatedResponse[GroupResponse])
async def list_groups(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(Group))).scalar_one()
    result = await db.execute(select(Group).order_by(Group.name).offset((page - 1) * per_page).limit(per_page))
    groups = result.scalars().all()

    # Single aggregate query — replaces one COUNT per group (N+1 fix)
    count_result = await db.execute(
        select(GroupMember.group_id, func.count(GroupMember.node_id).label("cnt")).group_by(GroupMember.group_id)
    )
    count_map = {row.group_id: row.cnt for row in count_result}

    items = [_to_response(g, count_map.get(g.id, 0)) for g in groups]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if payload.type == "dynamic":
        if not payload.predicate:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Dynamic groups require a predicate",
            )
        if not validate_predicate(payload.predicate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail='Predicate must be {"and":[...]} or {"or":[...]} with {"key":"...","value":"..."} items.',
            )
    group = Group(
        name=payload.name,
        description=payload.description,
        type=payload.type,
        predicate=payload.predicate,
        created_by=uuid.UUID(claims["sub"]),
    )
    from fleet_platform.core.audit import audit

    db.add(group)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group name already exists",
        )
    await audit(
        db,
        actor=claims["email"],
        action="group.create",
        resource_type="group",
        resource_id=group.id,
        new_value={"name": group.name, "type": group.type},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group name already exists",
        )
    await db.refresh(group)
    return _to_response(group, 0)


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    group = await _get_group_or_404(group_id, db)
    count = await _member_count(group_id, db)
    return _to_response(group, count)


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    from fleet_platform.core.audit import audit

    group = await _get_group_or_404(group_id, db)
    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    if payload.predicate is not None:
        group.predicate = payload.predicate
    await audit(
        db,
        actor=claims["email"],
        action="group.update",
        resource_type="group",
        resource_id=group_id,
        new_value=payload.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(group)
    count = await _member_count(group_id, db)
    return _to_response(group, count)


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    from fleet_platform.core.audit import audit

    group = await _get_group_or_404(group_id, db)

    # Invariant (#508): a node must always belong to ≥1 group.
    # Find members of this group whose ONLY group membership is this one.
    members_result = await db.execute(select(GroupMember).where(GroupMember.group_id == group_id))
    members = members_result.scalars().all()

    orphaned_node_ids: list[uuid.UUID] = []
    for m in members:
        count_result = await db.execute(select(func.count()).where(GroupMember.node_id == m.node_id))
        if count_result.scalar_one() <= 1:
            orphaned_node_ids.append(m.node_id)

    if orphaned_node_ids:
        n = len(orphaned_node_ids)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete group: {n} node(s) would be orphaned (left with no group). "
                f"Assign them to another group first. "
                f"Affected node IDs: {[str(nid) for nid in orphaned_node_ids]}"
            ),
        )

    await audit(
        db,
        actor=claims["email"],
        action="group.delete",
        resource_type="group",
        resource_id=group_id,
        old_value={"name": group.name, "type": group.type},
    )
    await db.delete(group)
    await db.commit()


@router.get("/{group_id}/nodes", response_model=PaginatedResponse[NodeListItem])
async def list_group_nodes(
    group_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    group = await _get_group_or_404(group_id, db)

    if group.type == "dynamic":
        node_ids = await resolve_dynamic_group(group.predicate or {}, db)
        base_query = select(Node).options(selectinload(Node.tags)).where(Node.id.in_(node_ids))
    else:
        base_query = (
            select(Node)
            .options(selectinload(Node.tags))
            .join(GroupMember, GroupMember.node_id == Node.id)
            .where(GroupMember.group_id == group_id)
        )

    total = (await db.execute(select(func.count()).select_from(base_query.subquery()))).scalar_one()
    result = await db.execute(base_query.offset((page - 1) * per_page).limit(per_page))
    nodes = result.scalars().all()
    return PaginatedResponse(
        items=[NodeListItem.model_validate(n) for n in nodes],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/{group_id}/members", status_code=201)
async def add_group_member(
    group_id: uuid.UUID,
    payload: GroupMemberAdd,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    group = await _get_group_or_404(group_id, db)
    if group.type == "dynamic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add members to a dynamic group",
        )
    existing = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.node_id == payload.node_id)
    )
    if existing.scalar_one_or_none():
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"status": "already_member"})
    db.add(GroupMember(group_id=group_id, node_id=payload.node_id, added_at=datetime.now(UTC)))
    await db.commit()
    return {"status": "added"}


@router.delete("/{group_id}/members/{node_id}", status_code=204)
async def remove_group_member(
    group_id: uuid.UUID,
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    group = await _get_group_or_404(group_id, db)
    if group.type == "dynamic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove members from a dynamic group",
        )

    # Invariant (#508): a node must always belong to ≥1 group.
    # Count the node's total group memberships before allowing removal.
    count_result = await db.execute(select(func.count()).where(GroupMember.node_id == node_id))
    membership_count = count_result.scalar_one()
    if membership_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Node must belong to at least one group; "
                "assign it to another group first before removing it from this one."
            ),
        )

    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.node_id == node_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await db.delete(member)
    await db.commit()


# ─── Group credential endpoints ────────────────────────────────────────────────


class GroupCredentialsUpdate(BaseModel):
    ssh_username: str | None = None
    ssh_password: str | None = None  # plaintext, encrypted on save
    ssh_auth_mode: str | None = None  # "password" | "key"
    ssh_key: str | None = None  # plaintext key, encrypted on save
    session_max_mins: int | None = None
    session_retention_days: int | None = None


@router.patch("/{group_id}/credentials", response_model=dict)
async def update_group_credentials(
    group_id: uuid.UUID,
    payload: GroupCredentialsUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Set SSH credentials for a group. All node members inherit these unless overridden."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # SSH credential updates (#725): inline ssh_* input is upserted into the
    # group's dedicated Credential row instead of the deprecated inline columns.
    # #985 Phase 2b: the group<->credential link is now read/written via the
    # credential_groups association (fleet_platform.services.credential_group_svc)
    # instead of the legacy Group.credential_id column — the column is kept
    # (unwritten) for expand-contract safety.
    current_credential_id = await get_group_credential_id(db, group.id)
    cred_id = await upsert_owner_ssh_credential(
        db,
        owner_name=f"group:{group.name}",
        current_credential_id=current_credential_id,
        ssh_username=payload.ssh_username,
        ssh_password=payload.ssh_password,
        ssh_key=payload.ssh_key,
        ssh_auth_mode=payload.ssh_auth_mode,
    )
    if cred_id is not None:
        await set_group_credential(db, group.id, cred_id)
    if payload.session_max_mins is not None:
        group.session_max_mins = payload.session_max_mins
    if payload.session_retention_days is not None:
        group.session_retention_days = payload.session_retention_days

    await db.commit()
    effective_credential_id = await get_group_credential_id(db, group.id)
    has_password, has_key = await owner_secret_flags(
        db,
        credential_id=effective_credential_id,
    )
    cred = await db.get(Credential, effective_credential_id) if effective_credential_id else None
    return {
        "group_id": str(group_id),
        "ssh_username": cred.username if cred else None,
        "has_ssh_password": has_password,
        "has_ssh_key": has_key,
        "ssh_auth_mode": "key" if has_key else "password",
        "session_max_mins": group.session_max_mins,
        "session_retention_days": group.session_retention_days,
    }


@router.get("/{group_id}/credentials", response_model=dict)
async def get_group_credentials(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Get credential metadata for a group (never returns secrets)."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    # #985 Phase 2b: read the effective credential via credential_groups (the
    # PATCH handler above no longer writes Group.credential_id).
    effective_credential_id = await get_group_credential_id(db, group.id)
    has_password, has_key = await owner_secret_flags(
        db,
        credential_id=effective_credential_id,
    )
    cred = await db.get(Credential, effective_credential_id) if effective_credential_id else None
    return {
        "group_id": str(group_id),
        "ssh_username": cred.username if cred else None,
        "has_ssh_password": has_password,
        "has_ssh_key": has_key,
        "ssh_auth_mode": "key" if has_key else "password",
        "session_max_mins": group.session_max_mins,
        "session_retention_days": group.session_retention_days,
        "credential_source": "group",
        "credential_id": str(effective_credential_id) if effective_credential_id else None,
    }
