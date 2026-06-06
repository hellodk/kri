"""Unit tests for playbook_catalog_svc — all DB calls mocked."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.playbook_catalog_svc import (
    auto_disable_missing,
    disable_playbook,
    enable_playbook,
)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_enable_playbook_creates_row(mock_db):
    """enable_playbook upserts a catalog row when none exists."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    fake_id = uuid.uuid4()
    instance = MagicMock()
    instance.id = fake_id
    instance.enabled = True

    with (
        patch("fleet_platform.services.playbook_catalog_svc.PlaybookCatalog") as MockCatalog,
        patch("fleet_platform.services.playbook_catalog_svc.select"),
    ):
        MockCatalog.return_value = instance

        result = await enable_playbook(
            mock_db,
            source_key="https://git.example.com/pulse.git",
            source_label="pulse",
            filename="bootstrap_mac.yml",
            entry_type="playbook",
            actor="admin@kri.local",
        )

    assert result.enabled is True
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_enable_playbook_updates_existing(mock_db):
    """enable_playbook sets enabled=True on an already-known row."""
    existing = MagicMock()
    existing.enabled = False
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = mock_result

    result = await enable_playbook(
        mock_db,
        source_key="https://git.example.com/pulse.git",
        source_label="pulse",
        filename="already_known.yml",
        entry_type="playbook",
        actor="admin@kri.local",
    )

    assert result.enabled is True
    mock_db.add.assert_not_called()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_disable_playbook_sets_enabled_false(mock_db):
    """disable_playbook sets enabled=False on an existing row."""
    catalog_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.id = catalog_id
    mock_row.enabled = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = mock_result

    await disable_playbook(mock_db, catalog_id=catalog_id, actor="admin@kri.local")

    assert mock_row.enabled is False
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_disable_playbook_returns_none_when_not_found(mock_db):
    """disable_playbook returns None for unknown catalog_id."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await disable_playbook(mock_db, catalog_id=uuid.uuid4(), actor="admin@kri.local")
    assert result is None


@pytest.mark.asyncio
async def test_auto_disable_missing_marks_gone_rows(mock_db):
    """auto_disable_missing disables rows whose filenames are not in discovered set."""
    catalog_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.id = catalog_id
    mock_row.filename = "deleted_playbook.yml"
    mock_row.enabled = True
    mock_row.auto_disabled_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    discovered = {"still_here.yml"}
    disabled = await auto_disable_missing(
        mock_db,
        source_key="https://git.example.com/pulse.git",
        discovered_filenames=discovered,
    )

    assert mock_row.enabled is False
    assert mock_row.auto_disabled_at is not None
    assert len(disabled) == 1
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_auto_disable_missing_skips_still_present(mock_db):
    """auto_disable_missing does not touch rows whose files still exist."""
    mock_row = MagicMock()
    mock_row.filename = "still_here.yml"
    mock_row.enabled = True

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    disabled = await auto_disable_missing(
        mock_db,
        source_key="https://git.example.com/pulse.git",
        discovered_filenames={"still_here.yml"},
    )

    assert mock_row.enabled is True
    assert len(disabled) == 0
    mock_db.commit.assert_not_called()
