# tests/unit/test_salt_keys_degraded.py
"""Tests for #452: salt_keys list_keys returns degraded flag on PermissionError."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_list_keys_returns_degraded_on_permission_error():
    """When PermissionError reading any bucket, degraded=True and degraded_reason is set."""
    from fleet_platform.api.routes.salt_keys import list_keys

    # Mock get_current_user to return a valid user dict
    with patch("fleet_platform.api.routes.salt_keys.get_current_user") as mock_get_user:
        mock_get_user.return_value = AsyncMock(return_value={})
        # Mock Path.exists to return True and iterdir to raise PermissionError
        with (
            patch("fleet_platform.api.routes.salt_keys.Path.exists", return_value=True),
            patch("fleet_platform.api.routes.salt_keys.Path.iterdir", side_effect=PermissionError("denied")),
        ):
            result = await list_keys(_={})

    assert result["degraded"] is True
    assert result["degraded_reason"] is not None
    assert "permission" in result["degraded_reason"].lower() or "PKI" in result["degraded_reason"]


@pytest.mark.asyncio
async def test_list_keys_not_degraded_on_success():
    """Normal case: no PermissionError → degraded=False."""
    from fleet_platform.api.routes.salt_keys import list_keys

    with patch("fleet_platform.api.routes.salt_keys.get_current_user") as mock_get_user:
        mock_get_user.return_value = AsyncMock(return_value={})
        with patch("fleet_platform.api.routes.salt_keys.Path.exists", return_value=False):
            result = await list_keys(_={})

    assert result["degraded"] is False
    assert result["degraded_reason"] is None


@pytest.mark.asyncio
async def test_list_keys_pending_count_present():
    """pending_count must always be present."""
    from fleet_platform.api.routes.salt_keys import list_keys

    with patch("fleet_platform.api.routes.salt_keys.get_current_user") as mock_get_user:
        mock_get_user.return_value = AsyncMock(return_value={})
        with patch("fleet_platform.api.routes.salt_keys.Path.exists", return_value=False):
            result = await list_keys(_={})

    assert "pending_count" in result
    assert isinstance(result["pending_count"], int)


@pytest.mark.asyncio
async def test_list_keys_degraded_buckets_return_empty_list():
    """A degraded bucket returns [] (not missing key) so callers don't KeyError."""
    from fleet_platform.api.routes.salt_keys import list_keys

    with patch("fleet_platform.api.routes.salt_keys.get_current_user") as mock_get_user:
        mock_get_user.return_value = AsyncMock(return_value={})
        with (
            patch("fleet_platform.api.routes.salt_keys.Path.exists", return_value=True),
            patch("fleet_platform.api.routes.salt_keys.Path.iterdir", side_effect=PermissionError("denied")),
        ):
            result = await list_keys(_={})

    assert "accepted" in result
    assert "pending" in result
    assert result["accepted"] == []
    assert result["pending"] == []
