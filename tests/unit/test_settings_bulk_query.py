"""Unit tests for get_settings_bulk — single DB round-trip for settings page (closes #284)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.services.platform_settings_svc import get_settings_bulk


@pytest.mark.asyncio
async def test_bulk_issues_single_execute_call():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    await get_settings_bulk(db, ["salt_master", "ssh_username", "vnc_enabled"])

    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_bulk_returns_none_for_missing_keys():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []  # no rows found
    db.execute = AsyncMock(return_value=result_mock)

    out = await get_settings_bulk(db, ["salt_master", "missing_key"])

    assert out["salt_master"] is None
    assert out["missing_key"] is None


@pytest.mark.asyncio
async def test_bulk_returns_plaintext_values():
    db = AsyncMock()
    row = MagicMock()
    row.key = "salt_master"
    row.value = "100.102.68.75"
    row.is_encrypted = False
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [row]
    db.execute = AsyncMock(return_value=result_mock)

    out = await get_settings_bulk(db, ["salt_master"])

    assert out["salt_master"] == "100.102.68.75"


@pytest.mark.asyncio
async def test_bulk_decrypts_encrypted_values():
    from fleet_platform.services.platform_settings_svc import _fernet

    plaintext = "s3cr3t-p4ssword"
    encrypted = _fernet().encrypt(plaintext.encode()).decode()

    db = AsyncMock()
    row = MagicMock()
    row.key = "ssh_password"
    row.value = encrypted
    row.is_encrypted = True
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [row]
    db.execute = AsyncMock(return_value=result_mock)

    out = await get_settings_bulk(db, ["ssh_password"])

    assert out["ssh_password"] == plaintext


@pytest.mark.asyncio
async def test_bulk_empty_keys_returns_empty_dict():
    db = AsyncMock()
    out = await get_settings_bulk(db, [])
    assert out == {}
    db.execute.assert_not_called()
