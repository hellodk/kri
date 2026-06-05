# tests/unit/test_health_tasks.py
"""Unit tests for collect_fleet_health Celery task. No subprocess, no network."""

from unittest.mock import MagicMock, patch


def test_collect_fleet_health_skips_when_no_online_nodes():
    from fleet_platform.workers.health_tasks import collect_fleet_health

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("fleet_platform.workers.health_tasks.get_sync_db", return_value=mock_db):
        result = collect_fleet_health()

    assert result == {"collected": 0}
    mock_db.add.assert_not_called()


def test_collect_fleet_health_inserts_snapshot_per_node():
    import uuid

    from fleet_platform.workers.health_tasks import collect_fleet_health

    node1 = MagicMock()
    node1.id = uuid.uuid4()
    node1.minion_id = "mac-mini-01"

    node2 = MagicMock()
    node2.id = uuid.uuid4()
    node2.minion_id = "mac-mini-02"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node1, node2]

    fake_metrics = {
        "mac-mini-01": {
            "disk_root_pct": 40,
            "mem_used_pct": 60,
            "cpu_load_1m": 1.2,
            "cpu_power_mw": 5000,
            "gpu_power_mw": 1500,
            "thermal_pressure": "Nominal",
            "gpu_name": "Apple M2 GPU",
            "gpu_vram_mb": 8192,
            "disk_root_used_gb": 100.0,
            "disk_root_total_gb": 256.0,
            "disk_root_inodes_pct": 1,
            "mem_total_gb": 16.0,
            "mem_available_gb": 6.4,
            "cpu_load_5m": 1.0,
            "cpu_load_15m": 0.8,
            "uptime_seconds": 172800,
            "error": None,
        },
        "mac-mini-02": {
            "disk_root_pct": 90,
            "mem_used_pct": 95,
            "cpu_load_1m": 3.5,
            "cpu_power_mw": None,
            "gpu_power_mw": None,
            "thermal_pressure": None,
            "gpu_name": None,
            "gpu_vram_mb": None,
            "disk_root_used_gb": 230.0,
            "disk_root_total_gb": 256.0,
            "disk_root_inodes_pct": 5,
            "mem_total_gb": 8.0,
            "mem_available_gb": 0.4,
            "cpu_load_5m": 3.0,
            "cpu_load_15m": 2.5,
            "uptime_seconds": 3600,
            "error": None,
        },
    }

    with (
        patch("fleet_platform.workers.health_tasks.get_sync_db", return_value=mock_db),
        patch(
            "fleet_platform.workers.health_tasks.salt_maintenance_svc.collect_all_metrics", return_value=fake_metrics
        ),
    ):
        result = collect_fleet_health()

    assert result == {"collected": 2}
    assert mock_db.add.call_count == 2
    mock_db.commit.assert_called_once()


def test_collect_fleet_health_task_name():
    from fleet_platform.workers.health_tasks import collect_fleet_health

    assert collect_fleet_health.name == "fleet_platform.workers.health_tasks.collect_fleet_health"
