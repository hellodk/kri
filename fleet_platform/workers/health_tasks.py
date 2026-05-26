# fleet_platform/workers/health_tasks.py
"""Celery task for periodic fleet health metric collection."""
import logging

from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
from fleet_platform.services import salt_maintenance_svc
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="fleet_platform.workers.health_tasks.collect_fleet_health",
    queue="maintenance",
)
def collect_fleet_health() -> dict:
    """Collect health metrics from all online nodes and persist snapshots.

    Runs as Celery beat task every 15 minutes. Also triggerable on-demand via API.
    """
    with get_sync_db() as db:
        nodes = db.execute(
            select(Node).where(Node.status == "online")
        ).scalars().all()

        if not nodes:
            logger.info("collect_fleet_health: no online nodes, skipping")
            return {"collected": 0}

        minion_ids = [n.minion_id for n in nodes]
        node_by_minion = {n.minion_id: n for n in nodes}

        logger.info("collect_fleet_health: collecting from %d nodes", len(nodes))
        health_data = salt_maintenance_svc.collect_all_metrics(minion_ids)

        count = 0
        for minion_id, metrics in health_data.items():
            node = node_by_minion.get(minion_id)
            if node is None:
                continue
            snapshot = NodeHealthSnapshot(
                node_id=node.id,
                minion_id=minion_id,
                disk_root_used_gb=metrics.get("disk_root_used_gb"),
                disk_root_total_gb=metrics.get("disk_root_total_gb"),
                disk_root_pct=metrics.get("disk_root_pct"),
                disk_root_inodes_pct=metrics.get("disk_root_inodes_pct"),
                mem_total_gb=metrics.get("mem_total_gb"),
                mem_available_gb=metrics.get("mem_available_gb"),
                mem_used_pct=metrics.get("mem_used_pct"),
                cpu_load_1m=metrics.get("cpu_load_1m"),
                cpu_load_5m=metrics.get("cpu_load_5m"),
                cpu_load_15m=metrics.get("cpu_load_15m"),
                uptime_seconds=metrics.get("uptime_seconds"),
                gpu_name=metrics.get("gpu_name"),
                gpu_vram_mb=metrics.get("gpu_vram_mb"),
                cpu_power_mw=metrics.get("cpu_power_mw"),
                gpu_power_mw=metrics.get("gpu_power_mw"),
                thermal_pressure=metrics.get("thermal_pressure"),
                error=metrics.get("error"),
            )
            db.add(snapshot)
            count += 1

        db.commit()
        logger.info("collect_fleet_health: stored %d snapshots", count)
        return {"collected": count}
