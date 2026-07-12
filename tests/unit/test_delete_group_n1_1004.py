# tests/unit/test_delete_group_n1_1004.py
"""Unit tests for #1004 A6 — delete_group must not issue one COUNT query per
member (N+1). It must use a single aggregate query (mirroring the existing
list_groups GROUP BY fix) that returns, per node in the group, its TOTAL
group-membership count — so the orphan invariant (#508) is still enforced in
exactly 2 round trips (group lookup + one aggregate), regardless of how many
members the group has.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.routes.groups import delete_group


def _make_group(name="prod", type_="static"):
    g = MagicMock()
    g.id = uuid.uuid4()
    g.name = name
    g.type = type_
    return g


def _claims():
    return {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}


class _MembershipTotalRow:
    """Mimics a SQLAlchemy (node_id, total) Row from the aggregate GROUP BY query."""

    def __init__(self, node_id, total):
        self.node_id = node_id
        self.total = total


async def test_delete_group_issues_exactly_two_execute_calls_regardless_of_member_count():
    """N+1 fix: whether the group has 1 member or 5, delete_group must call
    db.execute() exactly twice — the group lookup and ONE aggregate query —
    never once per member."""
    group = _make_group()
    node_ids = [uuid.uuid4() for _ in range(5)]

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    # All 5 nodes belong to >=2 groups -> nothing orphaned -> delete succeeds.
    aggregate_rows = [_MembershipTotalRow(nid, 2) for nid in node_ids]
    db.execute.side_effect = [group_result, aggregate_rows]

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        await delete_group(group_id=group.id, db=db, claims=_claims())

    assert db.execute.call_count == 2, "delete_group must not issue a COUNT query per member (N+1)"
    db.delete.assert_called_once_with(group)
    db.commit.assert_called_once()


async def test_delete_group_blocks_when_aggregate_finds_orphan():
    """A node whose aggregate total is 1 (this group is its ONLY membership)
    must still block deletion with 409, exactly as the old N+1 code did."""
    group = _make_group()
    orphan_node_id = uuid.uuid4()
    safe_node_id = uuid.uuid4()

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    aggregate_rows = [
        _MembershipTotalRow(orphan_node_id, 1),
        _MembershipTotalRow(safe_node_id, 2),
    ]
    db.execute.side_effect = [group_result, aggregate_rows]

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(group_id=group.id, db=db, claims=_claims())

    assert exc_info.value.status_code == 409
    assert str(orphan_node_id) in exc_info.value.detail
    assert str(safe_node_id) not in exc_info.value.detail
    db.delete.assert_not_called()
    db.commit.assert_not_called()


async def test_delete_group_blocked_detail_reports_correct_orphan_count():
    group = _make_group()
    orphan_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    aggregate_rows = [_MembershipTotalRow(nid, 1) for nid in orphan_ids]
    db.execute.side_effect = [group_result, aggregate_rows]

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(group_id=group.id, db=db, claims=_claims())

    assert "3" in exc_info.value.detail


async def test_delete_group_succeeds_when_no_members():
    """Empty group (aggregate query returns no rows) deletes cleanly."""
    group = _make_group()

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result, []]

    with patch("fleet_platform.core.audit.audit", new=AsyncMock()):
        await delete_group(group_id=group.id, db=db, claims=_claims())

    assert db.execute.call_count == 2
    db.delete.assert_called_once_with(group)
    db.commit.assert_called_once()
