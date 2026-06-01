"""Unit tests for macOS configuration profile service functions."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_extract_profile_uuid_valid_xml():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    xml = """<?xml version="1.0"?>
<plist version="1.0"><dict>
<key>PayloadUUID</key><string>12345678-ABCD-1234-ABCD-123456789012</string>
</dict></plist>"""
    assert extract_profile_uuid(xml) == "12345678-ABCD-1234-ABCD-123456789012"


def test_extract_profile_uuid_missing_returns_none():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    assert extract_profile_uuid("<plist><dict></dict></plist>") is None


def test_extract_profile_uuid_invalid_xml_returns_none():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    assert extract_profile_uuid("not xml at all") is None


def test_extract_profile_uuid_nested_dict():
    """PayloadUUID nested inside an array/dict should still be found."""
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    xml = """<?xml version="1.0"?>
<plist version="1.0">
  <dict>
    <key>PayloadContent</key>
    <array>
      <dict>
        <key>PayloadUUID</key>
        <string>NESTED-1234-ABCD-1234-NESTED123456</string>
      </dict>
    </array>
    <key>PayloadUUID</key>
    <string>TOP-LEVEL-ABCD-1234-ABCD-TOPLEVEL0001</string>
  </dict>
</plist>"""
    # Should return the first match (top-level dict)
    result = extract_profile_uuid(xml)
    assert result is not None
    assert len(result) > 0


def test_extract_profile_uuid_empty_string_returns_none():
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    assert extract_profile_uuid("") is None


def test_extract_profile_uuid_only_key_no_string():
    """PayloadUUID key exists but no following <string> sibling."""
    from fleet_platform.services.mobileconfig_svc import extract_profile_uuid

    xml = """<plist><dict>
<key>PayloadUUID</key>
<integer>12345</integer>
</dict></plist>"""
    assert extract_profile_uuid(xml) is None


# ── Async service function tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_profile_adds_and_commits():
    from fleet_platform.schemas.mobileconfig import MobileconfigProfileCreate
    from fleet_platform.services.mobileconfig_svc import create_profile

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    payload = MobileconfigProfileCreate(
        name="Test Profile",
        description="desc",
        payload_xml="<plist><dict></dict></plist>",
    )
    await create_profile(db, payload)
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_list_profiles_calls_db():
    from fleet_platform.services.mobileconfig_svc import list_profiles

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    profiles = await list_profiles(db)
    assert profiles == []
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_profile_returns_none_when_missing():
    from fleet_platform.services.mobileconfig_svc import get_profile

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    assert await get_profile(db, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_delete_profile_noop_when_not_found():
    from fleet_platform.services.mobileconfig_svc import delete_profile

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    await delete_profile(db, uuid.uuid4())
    db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_assign_to_group_returns_existing():
    from fleet_platform.services.mobileconfig_svc import assign_to_group

    db = AsyncMock()
    existing_assignment = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_assignment
    db.execute = AsyncMock(return_value=mock_result)
    result = await assign_to_group(db, uuid.uuid4(), uuid.uuid4(), "admin")
    assert result is existing_assignment
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_assign_to_group_creates_new():
    from fleet_platform.services.mobileconfig_svc import assign_to_group

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # not existing
    db.execute = AsyncMock(return_value=mock_result)
    await assign_to_group(db, uuid.uuid4(), uuid.uuid4(), "admin")
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_profile_deletes_when_found():
    from fleet_platform.services.mobileconfig_svc import delete_profile

    db = AsyncMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    mock_profile = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_profile
    db.execute = AsyncMock(return_value=mock_result)
    await delete_profile(db, uuid.uuid4())
    db.delete.assert_called_once_with(mock_profile)
    db.commit.assert_called_once()
