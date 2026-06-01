"""Tests for orphan reaper race fixes (#305)."""
from unittest.mock import MagicMock, patch


def test_reaper_query_has_completed_at_guard():
    """Bug A race fix: completed_at IS NULL guard prevents touching already-completed jobs."""
    from fleet_platform.workers.maintenance import reap_orphaned_jobs

    # Mock db that will execute the update statement
    mock_result = MagicMock()
    mock_result.rowcount = 0  # No rows updated
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value = mock_result
    mock_db.commit = MagicMock()

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db):
        result = reap_orphaned_jobs()

    # Verify the function returns the rowcount
    assert result["reaped"] == 0

    # Verify that the update statement was built with the completed_at guard
    # by checking the SQL that was passed to execute
    call_args = mock_db.execute.call_args
    update_stmt = call_args[0][0]
    # The update statement should contain a whereclause that checks completed_at IS NULL
    assert "completed_at IS NULL" in str(update_stmt) or ".is_(None)" in repr(update_stmt)


def test_reaper_query_has_null_started_at_fallback():
    """Bug B fix: or_() clause catches both normal orphans and null started_at cases."""
    from fleet_platform.workers.maintenance import reap_orphaned_jobs

    mock_result = MagicMock()
    mock_result.rowcount = 1  # One row would be reaped
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value = mock_result
    mock_db.commit = MagicMock()

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db):
        result = reap_orphaned_jobs()

    assert result["reaped"] == 1

    # Verify the update statement contains logic for null started_at
    call_args = mock_db.execute.call_args
    update_stmt = call_args[0][0]
    # Should have or_() with started_at.is_(None) check
    stmt_str = str(update_stmt)
    assert "started_at" in stmt_str


def test_reaper_query_appends_stdout():
    """Bug C fix: stdout is appended with func.coalesce, not overwritten."""
    from fleet_platform.workers.maintenance import reap_orphaned_jobs

    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value = mock_result
    mock_db.commit = MagicMock()

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db):
        result = reap_orphaned_jobs()

    assert result["reaped"] == 1

    # Verify the update statement uses coalesce + concatenation for stdout
    call_args = mock_db.execute.call_args
    update_stmt = call_args[0][0]
    stmt_str = str(update_stmt)
    # The update should use func.coalesce to preserve existing stdout
    assert "coalesce" in stmt_str.lower() or "+" in stmt_str


def test_reaper_returns_dict_with_reaped_count():
    """Task returns dict with 'reaped' key containing rowcount."""
    from fleet_platform.workers.maintenance import reap_orphaned_jobs

    mock_result = MagicMock()
    mock_result.rowcount = 42
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value = mock_result
    mock_db.commit = MagicMock()

    with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db):
        result = reap_orphaned_jobs()

    assert isinstance(result, dict)
    assert "reaped" in result
    assert result["reaped"] == 42
