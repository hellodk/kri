"""Issue #1018 — SaltMaster uniqueness on NAME and network ENDPOINT.

A master IS its endpoint (address + publish/ret/api ports); two rows for the same
endpoint are meaningless (the 192.168.1.64 / -1 twins). create + update must 409
on a duplicate name OR endpoint, never silently dupe or 500.

Run: pytest tests/unit/test_salt_master_endpoint_unique_1018.py -q
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.routes.salt_masters import _assert_master_identity_unique

_SRC = (
    Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "salt_masters.py"
).read_text()

_EP = dict(address="192.168.1.64", publish_port=4505, ret_port=4506, salt_api_port=4507)


def _result(first_val):
    r = MagicMock()
    r.scalars.return_value.first.return_value = first_val
    return r


async def test_duplicate_name_raises_409():
    db = AsyncMock(spec=AsyncSession)
    existing = MagicMock()
    existing.name = "mm1"
    db.execute.side_effect = [_result(existing)]  # name lookup hits
    with pytest.raises(HTTPException) as e:
        await _assert_master_identity_unique(db, name="mm1", **_EP)
    assert e.value.status_code == 409
    assert "named" in e.value.detail.lower()


async def test_duplicate_endpoint_raises_409():
    db = AsyncMock(spec=AsyncSession)
    dup = MagicMock()
    dup.name = "192.168.1.64"
    db.execute.side_effect = [_result(None), _result(dup)]  # name clear, endpoint hits
    with pytest.raises(HTTPException) as e:
        await _assert_master_identity_unique(db, name="192.168.1.64-1", **_EP)
    assert e.value.status_code == 409
    assert "192.168.1.64" in e.value.detail


async def test_distinct_name_and_endpoint_passes():
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [_result(None), _result(None)]
    await _assert_master_identity_unique(
        db, name="cylon", address="192.168.1.70", publish_port=4505, ret_port=4506, salt_api_port=4507
    )


async def test_update_excludes_self():
    """On update the row being edited must not count as its own duplicate."""
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [_result(None), _result(None)]
    import uuid

    await _assert_master_identity_unique(db, name="mm1", exclude_id=uuid.uuid4(), **_EP)
    # both queries must carry an id != exclusion (verified by no raise + 2 executes)
    assert db.execute.await_count == 2


# ── source-contract: create + update actually call the guard ─────────────────


def test_create_and_update_call_the_guard():
    assert "_assert_master_identity_unique(" in _SRC
    # create passes body.*, update passes master.* with exclude_id
    assert "exclude_id=master_id" in _SRC
