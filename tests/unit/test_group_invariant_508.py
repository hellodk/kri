# tests/unit/test_group_invariant_508.py
"""
Unit tests for the node-must-belong-to-≥1-group invariant (issue #508).

Strategy: mock the AsyncSession to return controlled COUNT values so these
tests run without a real database.  We exercise the guard logic in the two
route handlers:
  - remove_group_member  (DELETE /groups/{group_id}/members/{node_id})
  - delete_group         (DELETE /groups/{group_id})
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_group(type_: str = "static", name: str = "g1") -> MagicMock:
    g = MagicMock()
    g.id = uuid.uuid4()
    g.name = name
    g.type = type_
    return g


def _make_member(group_id: uuid.UUID, node_id: uuid.UUID) -> MagicMock:
    m = MagicMock()
    m.group_id = group_id
    m.node_id = node_id
    return m


def _db_with_execute_sequence(*return_values):
    """Return a mock AsyncSession whose .execute() returns each value in turn."""
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = list(return_values)
    return db


def _scalar_result(value):
    """Wrap a scalar so result.scalar_one() == value."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalar_one_or_none_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_all_result(items):
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


# ---------------------------------------------------------------------------
# remove_group_member — node's ONLY group → must raise 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_last_group_raises_409():
    """Removing a node from its only group must be rejected with HTTP 409.

    The guard fires BEFORE the GroupMember lookup, so execute is called twice:
    once for _get_group_or_404 and once for the membership count.
    """
    from fleet_platform.api.routes.groups import remove_group_member

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1  # only 1 group → must block

    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [group_result, count_result]

    with pytest.raises(HTTPException) as exc_info:
        await remove_group_member(
            group_id=group_id,
            node_id=node_id,
            db=db,
            _={"sub": str(uuid.uuid4()), "email": "test@example.com", "role": "admin"},
        )

    assert exc_info.value.status_code == 409
    assert "at least one group" in exc_info.value.detail.lower()
    # Membership must NOT have been deleted
    db.delete.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_remove_last_group_membership_not_deleted():
    """Verify db.delete is never called when the 409 guard fires."""
    from fleet_platform.api.routes.groups import remove_group_member

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [group_result, count_result]

    with pytest.raises(HTTPException):
        await remove_group_member(
            group_id=group_id,
            node_id=node_id,
            db=db,
            _={"sub": str(uuid.uuid4()), "email": "test@example.com", "role": "admin"},
        )

    db.delete.assert_not_called()


# ---------------------------------------------------------------------------
# remove_group_member — node belongs to ≥2 groups → success (204)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_with_other_groups_succeeds():
    """Removing a node that still belongs to another group must succeed (no exception)."""
    from fleet_platform.api.routes.groups import remove_group_member

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group

    count_result = MagicMock()
    count_result.scalar_one.return_value = 2  # belongs to 2 groups — safe to remove

    member = _make_member(group_id, node_id)
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = member

    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [group_result, count_result, member_result]

    # Should not raise
    await remove_group_member(
        group_id=group_id,
        node_id=node_id,
        db=db,
        _={"sub": str(uuid.uuid4()), "email": "test@example.com", "role": "admin"},
    )

    # db.delete must have been called exactly once (with whatever member object the impl fetched)
    assert db.delete.call_count == 1
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_remove_member_count_three_succeeds():
    """Node in 3 groups: removing one group membership must succeed."""
    from fleet_platform.api.routes.groups import remove_group_member

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group

    count_result = MagicMock()
    count_result.scalar_one.return_value = 3

    member = _make_member(group_id, node_id)
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = member

    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [group_result, count_result, member_result]

    await remove_group_member(
        group_id=group_id,
        node_id=node_id,
        db=db,
        _={"sub": str(uuid.uuid4()), "email": "test@example.com", "role": "admin"},
    )

    assert db.delete.call_count == 1


# ---------------------------------------------------------------------------
# remove_group_member — dynamic group → blocked before count check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_from_dynamic_group_raises_400():
    """Dynamic group: existing rejection still works (not affected by #508 guard)."""
    from fleet_platform.api.routes.groups import remove_group_member

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group(type_="dynamic")
    group.id = group_id

    db = _db_with_execute_sequence(
        _scalar_one_or_none_result(group),  # _get_group_or_404
    )

    with pytest.raises(HTTPException) as exc_info:
        await remove_group_member(
            group_id=group_id,
            node_id=node_id,
            db=db,
            _={"sub": str(uuid.uuid4()), "email": "test@example.com", "role": "admin"},
        )

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# delete_group — has member whose only group is this one → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_group_with_sole_member_node_raises_409():
    """Deleting a group that is some node's only group must be rejected with HTTP 409."""
    from fleet_platform.api.routes.groups import delete_group

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    # Build a mock member row with .node_id attribute
    member_row = MagicMock()
    member_row.node_id = node_id

    # execute call 1: _get_group_or_404
    # execute call 2: fetch all GroupMember rows for this group → [member_row]
    # execute call 3: count of node_id's total memberships → 1  (only this group)
    db = _db_with_execute_sequence(
        _scalar_one_or_none_result(group),  # _get_group_or_404
        _scalars_all_result([member_row]),  # members of this group
        _scalar_result(1),  # membership count for node_id
    )

    claims = {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(group_id=group_id, db=db, claims=claims)

    assert exc_info.value.status_code == 409
    assert "orphan" in exc_info.value.detail.lower() or "group" in exc_info.value.detail.lower()
    db.delete.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_delete_group_blocked_lists_affected_count():
    """The 409 detail must mention how many nodes would be orphaned."""
    from fleet_platform.api.routes.groups import delete_group

    group_id = uuid.uuid4()
    node_id_a = uuid.uuid4()
    node_id_b = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    # Two nodes, each belonging only to this group
    member_a = MagicMock()
    member_a.node_id = node_id_a
    member_b = MagicMock()
    member_b.node_id = node_id_b

    # execute sequence: get_group, members list, count for a, count for b
    db = _db_with_execute_sequence(
        _scalar_one_or_none_result(group),
        _scalars_all_result([member_a, member_b]),
        _scalar_result(1),  # node_a has 1 membership
        _scalar_result(1),  # node_b has 1 membership
    )

    claims = {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(group_id=group_id, db=db, claims=claims)

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    # Must mention the count (2) or both node IDs
    assert "2" in detail or str(node_id_a) in detail or str(node_id_b) in detail


@pytest.mark.asyncio
async def test_delete_group_with_multi_group_nodes_succeeds():
    """Deleting a group whose members all have another group must succeed."""
    from fleet_platform.api.routes.groups import delete_group

    group_id = uuid.uuid4()
    node_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    member_row = MagicMock()
    member_row.node_id = node_id

    # count = 2 → this node still belongs to another group after deletion
    db = _db_with_execute_sequence(
        _scalar_one_or_none_result(group),
        _scalars_all_result([member_row]),
        _scalar_result(2),  # node belongs to 2 groups — safe to remove from this one
    )

    claims = {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        await delete_group(group_id=group_id, db=db, claims=claims)

    db.delete.assert_called_once_with(group)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_empty_group_succeeds():
    """Deleting a group with no members must succeed (no orphan risk)."""
    from fleet_platform.api.routes.groups import delete_group

    group_id = uuid.uuid4()
    group = _make_group()
    group.id = group_id

    db = _db_with_execute_sequence(
        _scalar_one_or_none_result(group),  # _get_group_or_404
        _scalars_all_result([]),  # no members
    )

    claims = {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        await delete_group(group_id=group_id, db=db, claims=claims)

    db.delete.assert_called_once_with(group)
    db.commit.assert_called_once()
