"""Unit tests for #144 (retention) and #146 (thundering herd)."""
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_cleanup_task_exists():
    from fleet_platform.workers.health_tasks import cleanup_old_health_snapshots
    assert callable(cleanup_old_health_snapshots)


def test_cleanup_task_uses_90_day_cutoff():
    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value = mock_result

    with patch("fleet_platform.workers.health_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.health_tasks import cleanup_old_health_snapshots
        result = cleanup_old_health_snapshots()

    assert result == 5
    call_kwargs = mock_db.execute.call_args[0][1]
    cutoff = call_kwargs["cutoff"]
    assert (datetime.utcnow() - cutoff).days >= 89  # ~90 days ago


def test_cleanup_scheduled_in_beat():
    src = Path("fleet_platform/workers/celery_app.py").read_text()
    assert "cleanup_old_health_snapshots" in src, "cleanup task must be in beat schedule"


def test_collect_all_metrics_has_batch_constant():
    src = Path("fleet_platform/workers/health_tasks.py").read_text()
    assert "BATCH_SIZE" in src or "batch_size" in src, (
        "collect_all_metrics must use batching to avoid thundering herd"
    )
