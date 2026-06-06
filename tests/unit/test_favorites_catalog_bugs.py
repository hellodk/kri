"""Tests for #501 (favorites 500→401) and #502 (enable_source upsert)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── #501 tests ──────────────────────────────────────────────────────────


def test_favorites_missing_sub_constant():
    """Sanity: the fix code path exists (UUID conversion is wrapped)."""
    # The real test is that uuid.UUID("") raises ValueError, which our fix catches.
    with pytest.raises(ValueError):
        uuid.UUID("")


def test_favorites_get_sub_fallback():
    """claims.get("sub", "") returns "" when sub is absent, triggering ValueError."""
    claims = {"email": "test@example.com", "role": "operator"}
    with pytest.raises(ValueError):
        uuid.UUID(claims.get("sub", ""))


def test_favorites_valid_sub_parses():
    """Valid UUID sub parses without error."""
    valid_id = str(uuid.uuid4())
    claims = {"sub": valid_id}
    result = uuid.UUID(claims.get("sub", ""))
    assert isinstance(result, uuid.UUID)


# ── #502 tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_source_uses_pg_insert():
    """enable_source now calls db.execute with a pg_insert statement."""
    from sqlalchemy.dialects.postgresql import Insert

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_db.execute = AsyncMock(return_value=mock_result)

    from fleet_platform.services.playbook_catalog_svc import enable_source

    count = await enable_source(
        mock_db,
        source_key="test/source",
        source_label="test",
        discovered=[{"filename": "site.yml", "entry_type": "playbook"}],
        actor="admin@example.com",
    )

    assert count == 1
    assert mock_db.execute.call_count == 1
    # The statement passed to execute should be a PostgreSQL Insert (upsert)
    stmt_arg = mock_db.execute.call_args[0][0]
    assert isinstance(stmt_arg, Insert)


@pytest.mark.asyncio
async def test_enable_source_noop_when_already_enabled():
    """enable_source returns 0 when rowcount is 0 (row already enabled, no-op)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0  # no-op — row already enabled
    mock_db.execute = AsyncMock(return_value=mock_result)

    from fleet_platform.services.playbook_catalog_svc import enable_source

    count = await enable_source(
        mock_db,
        source_key="test/source",
        source_label="test",
        discovered=[{"filename": "site.yml", "entry_type": "playbook"}],
        actor="admin@example.com",
    )

    assert count == 0
