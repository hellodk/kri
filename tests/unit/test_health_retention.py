"""Behavioral tests for #144 (retention) and #146 (thundering herd).

Replaces source-scrape checks (``"cleanup_old_health_snapshots" in src`` /
``"BATCH_SIZE" in src``) with assertions on the real beat schedule object and
the real batching behaviour of ``collect_fleet_health``.
"""

from datetime import datetime
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
    """The cleanup task must be wired into the real Celery beat schedule."""
    from fleet_platform.workers.celery_app import celery_app

    beat = celery_app.conf.beat_schedule
    tasks = {entry["task"] for entry in beat.values()}
    assert "fleet_platform.workers.health_tasks.cleanup_old_health_snapshots" in tasks, (
        "cleanup task must be in beat schedule"
    )


def test_collect_fleet_health_scheduled_in_beat():
    from fleet_platform.workers.celery_app import celery_app

    beat = celery_app.conf.beat_schedule
    tasks = {entry["task"] for entry in beat.values()}
    assert "fleet_platform.workers.health_tasks.collect_fleet_health" in tasks


def test_batch_size_is_a_positive_int():
    """The thundering-herd guard constant must exist and be a sane batch size."""
    from fleet_platform.workers.health_tasks import BATCH_SIZE

    assert isinstance(BATCH_SIZE, int)
    assert BATCH_SIZE > 0


def test_collect_fleet_health_batches_salt_calls():
    """collect_fleet_health must split nodes into batches of <= BATCH_SIZE so it
    never fans out a Salt command to every minion at once (thundering herd)."""
    from fleet_platform.workers import health_tasks
    from fleet_platform.workers.health_tasks import BATCH_SIZE

    n_nodes = BATCH_SIZE * 2 + 3  # forces 3 batches
    nodes = []
    for i in range(n_nodes):
        node = MagicMock()
        node.id = i
        node.minion_id = f"minion-{i}"
        nodes.append(node)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = nodes

    batch_sizes: list[int] = []

    def _fake_collect(batch):
        batch_sizes.append(len(batch))
        return {m: {} for m in batch}

    with (
        patch.object(health_tasks, "get_sync_db", return_value=mock_db),
        patch.object(health_tasks.salt_maintenance_svc, "collect_all_metrics", side_effect=_fake_collect),
        patch.object(health_tasks.time, "sleep"),
    ):
        result = health_tasks.collect_fleet_health()

    # 3 batches: BATCH_SIZE, BATCH_SIZE, 3
    assert len(batch_sizes) == 3
    assert max(batch_sizes) <= BATCH_SIZE
    assert sum(batch_sizes) == n_nodes
    assert result == {"collected": n_nodes}


def test_collect_fleet_health_no_online_nodes_short_circuits():
    from fleet_platform.workers import health_tasks

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    with (
        patch.object(health_tasks, "get_sync_db", return_value=mock_db),
        patch.object(health_tasks.salt_maintenance_svc, "collect_all_metrics") as mock_collect,
    ):
        result = health_tasks.collect_fleet_health()

    assert result == {"collected": 0}
    mock_collect.assert_not_called()
