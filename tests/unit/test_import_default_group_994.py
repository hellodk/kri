"""Issue #994 (review finding C4) — import never leaves a node group-less.

`import_commit` falls back to the seeded 'default' group for rows with no
group_id. Previously it skipped silently when that seed was absent, leaving the
node in NO group (violating the node-in-≥1-group invariant) and dereferencing a
possibly-None group (`_grp.name`) → mypy union-attr + runtime crash.

`_get_or_create_default_group` now guarantees the group exists.

Run: pytest tests/unit/test_import_default_group_994.py -q
"""

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.routes.fleet import _get_or_create_default_group


async def test_creates_default_group_when_absent():
    db = AsyncMock(spec=AsyncSession)
    res = MagicMock()
    res.scalar_one_or_none.return_value = None  # no seeded 'default' group
    db.execute.return_value = res

    grp = await _get_or_create_default_group(db)

    assert grp.name == "default"
    assert grp.type == "static"
    db.add.assert_called_once_with(grp)
    db.flush.assert_awaited_once()


async def test_returns_existing_default_group_idempotently():
    existing = MagicMock()
    existing.name = "default"
    db = AsyncMock(spec=AsyncSession)
    res = MagicMock()
    res.scalar_one_or_none.return_value = existing
    db.execute.return_value = res

    grp = await _get_or_create_default_group(db)

    assert grp is existing
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
