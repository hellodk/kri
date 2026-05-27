import pytest
from unittest.mock import MagicMock, patch


def test_placeholder():
    """Placeholder — will be expanded in T4."""
    pass


def test_get_setting_sync_returns_none_when_missing():
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = get_setting_sync(mock_db, "nonexistent_key")
    assert result is None


def test_get_setting_sync_returns_plaintext():
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    row = MagicMock(spec=PlatformSetting)
    row.is_encrypted = False
    row.value = "smtp.example.com"

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = row

    result = get_setting_sync(mock_db, "smtp_host")
    assert result == "smtp.example.com"
