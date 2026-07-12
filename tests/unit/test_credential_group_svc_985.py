"""Unit tests for #985 Phase 2b — credential_groups write path + usage counts.

Covers ``fleet_platform.services.credential_group_svc`` (the new read/write
helpers over the ``credential_groups`` association) and source-contract checks
that ``groups.py`` / ``credentials.py`` were migrated to use them instead of
the legacy ``Group.credential_id`` column.
"""

import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_group_svc import (
    count_groups_for_credential,
    count_nodes_for_credential,
    get_group_credential_id,
    set_group_credential,
)

# ---------------------------------------------------------------------------
# set_group_credential
# ---------------------------------------------------------------------------


async def test_set_group_credential_inserts_mapping():
    db = AsyncMock(spec=AsyncSession)
    group_id = uuid.uuid4()
    credential_id = uuid.uuid4()

    await set_group_credential(db, group_id, credential_id)

    db.execute.assert_awaited_once()  # the DELETE
    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.group_id == group_id
    assert added.credential_id == credential_id


async def test_set_group_credential_replaces_existing_mapping():
    """Calling again with a different credential deletes the old row first,
    then inserts the new one — respects UNIQUE(group_id)."""
    db = AsyncMock(spec=AsyncSession)
    group_id = uuid.uuid4()
    cred_a = uuid.uuid4()
    cred_b = uuid.uuid4()

    await set_group_credential(db, group_id, cred_a)
    await set_group_credential(db, group_id, cred_b)

    assert db.execute.await_count == 2  # one DELETE per call
    assert db.add.call_count == 2
    last_added = db.add.call_args[0][0]
    assert last_added.credential_id == cred_b
    assert last_added.group_id == group_id


async def test_set_group_credential_none_removes_mapping():
    db = AsyncMock(spec=AsyncSession)
    group_id = uuid.uuid4()

    await set_group_credential(db, group_id, None)

    db.execute.assert_awaited_once()  # the DELETE
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# get_group_credential_id
# ---------------------------------------------------------------------------


async def test_get_group_credential_id_returns_mapped_credential():
    db = AsyncMock(spec=AsyncSession)
    credential_id = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = credential_id
    db.execute.return_value = result

    got = await get_group_credential_id(db, uuid.uuid4())

    assert got == credential_id


async def test_get_group_credential_id_returns_none_when_unmapped():
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    got = await get_group_credential_id(db, uuid.uuid4())

    assert got is None


# ---------------------------------------------------------------------------
# count_groups_for_credential / count_nodes_for_credential
# ---------------------------------------------------------------------------


async def test_count_groups_for_credential_across_two_groups():
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one.return_value = 2
    db.execute.return_value = result

    count = await count_groups_for_credential(db, uuid.uuid4())

    assert count == 2


async def test_count_nodes_for_credential_across_groups_and_members():
    """Two groups mapped to the same credential, with distinct node membership
    across them — count_nodes_for_credential returns the distinct node total."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one.return_value = 3  # e.g. group A has 2 nodes, group B has 1 (distinct)
    db.execute.return_value = result

    count = await count_nodes_for_credential(db, uuid.uuid4())

    assert count == 3


# ---------------------------------------------------------------------------
# Source-contract: groups.py / credentials.py migrated off Group.credential_id
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GROUPS_PY = _REPO_ROOT / "fleet_platform" / "api" / "routes" / "groups.py"
_CREDENTIALS_PY = _REPO_ROOT / "fleet_platform" / "api" / "routes" / "credentials.py"


def test_groups_py_uses_credential_group_svc_helpers():
    src = _GROUPS_PY.read_text()
    assert "from fleet_platform.services.credential_group_svc import" in src
    assert "get_group_credential_id" in src
    assert "set_group_credential" in src


def test_groups_py_patch_handler_no_longer_writes_group_credential_id_column():
    """The credential PATCH handler must not assign to group.credential_id
    directly anymore — writes go through set_group_credential()."""
    src = _GROUPS_PY.read_text()
    assert re.search(r"group\.credential_id\s*=\s*cred_id", src) is None


def test_credentials_py_reference_counts_uses_association_helpers():
    src = _CREDENTIALS_PY.read_text()
    assert "count_groups_for_credential" in src
    assert "count_nodes_for_credential" in src
    # The legacy direct Group.credential_id FK count must be gone.
    assert "Group.credential_id == credential_id" not in src
