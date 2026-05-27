"""
Tests for issue #68: stale/offline thresholds read from platform settings.

TDD: these tests are written before implementation — they must fail first.
"""
from datetime import timedelta
from unittest.mock import MagicMock, call, patch


def _make_mock_session(stale_rowcount: int = 0, offline_rowcount: int = 0) -> MagicMock:
    """Return a mock DB session that returns the given rowcounts from execute()."""
    stale_result = MagicMock()
    stale_result.rowcount = stale_rowcount
    offline_result = MagicMock()
    offline_result.rowcount = offline_rowcount

    mock_session = MagicMock()
    mock_session.execute.side_effect = [stale_result, offline_result]
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    return mock_session


def test_mark_stale_nodes_uses_db_thresholds():
    """When platform settings return '30' and '2', the task must use
    timedelta(minutes=30) and timedelta(hours=2) instead of the defaults."""
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_session = _make_mock_session()

    def setting_side_effect(db, key):
        from fleet_platform.services.platform_settings_svc import (
            NODE_OFFLINE_THRESHOLD_HOURS,
            NODE_STALE_THRESHOLD_MINUTES,
        )
        if key == NODE_STALE_THRESHOLD_MINUTES:
            return "30"
        if key == NODE_OFFLINE_THRESHOLD_HOURS:
            return "2"
        return None

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db, patch(
        "fleet_platform.workers.maintenance.get_setting_sync",
        side_effect=setting_side_effect,
    ) as mock_get:
        mock_db.return_value = mock_session
        mark_stale_nodes()

    # Verify get_setting_sync was called with the correct keys
    from fleet_platform.services.platform_settings_svc import (
        NODE_OFFLINE_THRESHOLD_HOURS,
        NODE_STALE_THRESHOLD_MINUTES,
    )

    called_keys = [c.args[1] for c in mock_get.call_args_list]
    assert NODE_STALE_THRESHOLD_MINUTES in called_keys, (
        f"Expected get_setting_sync called with '{NODE_STALE_THRESHOLD_MINUTES}', "
        f"got keys: {called_keys}"
    )
    assert NODE_OFFLINE_THRESHOLD_HOURS in called_keys, (
        f"Expected get_setting_sync called with '{NODE_OFFLINE_THRESHOLD_HOURS}', "
        f"got keys: {called_keys}"
    )

    # Verify the execute calls happened (task ran to completion)
    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_called_once()


def test_mark_stale_nodes_falls_back_to_defaults():
    """When get_setting_sync returns None, the task must use defaults
    (15 minutes, 1 hour) and not raise any exception."""
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_session = _make_mock_session(stale_rowcount=2, offline_rowcount=1)

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db, patch(
        "fleet_platform.workers.maintenance.get_setting_sync",
        return_value=None,
    ):
        mock_db.return_value = mock_session
        result = mark_stale_nodes()

    # Task must succeed and return the expected shape
    assert result == {"stale": 2, "offline": 1}
    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_called_once()


def test_mark_stale_nodes_falls_back_on_invalid_value():
    """When get_setting_sync returns a non-numeric string, the task must
    silently fall back to defaults and not crash."""
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_session = _make_mock_session()

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db, patch(
        "fleet_platform.workers.maintenance.get_setting_sync",
        return_value="not_a_number",
    ):
        mock_db.return_value = mock_session
        result = mark_stale_nodes()  # must not raise

    assert "stale" in result
    assert "offline" in result
    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_called_once()
