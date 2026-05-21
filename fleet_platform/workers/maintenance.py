from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.bootstrap_run import BootstrapRun
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.workers.celery_app import celery_app

_STALE_THRESHOLD = timedelta(minutes=15)
_OFFLINE_THRESHOLD = timedelta(hours=1)


@celery_app.task(name="fleet_platform.workers.maintenance.mark_stale_nodes")
def mark_stale_nodes() -> dict:
    """Mark nodes as stale or offline based on last_seen_at. Runs every 5 minutes via beat."""
    now = datetime.now(UTC)
    stale_cutoff = now - _STALE_THRESHOLD
    offline_cutoff = now - _OFFLINE_THRESHOLD

    with get_sync_db() as db:
        # NOTE: Nodes with last_seen_at IS NULL (registered but never reported) are
        # intentionally not touched here. They stay in status="unknown" indefinitely.
        # A separate cleanup task (Plan 3+) should evict nodes that are unknown for
        # longer than the offline threshold.
        stale = db.execute(
            update(Node)
            .where(Node.last_seen_at < stale_cutoff)
            .where(Node.last_seen_at >= offline_cutoff)
            .where(Node.status == "online")
            .values(status="stale", updated_at=now)
        )
        offline = db.execute(
            update(Node)
            .where(Node.last_seen_at < offline_cutoff)
            .where(Node.status.in_(["online", "stale"]))
            .values(status="offline", updated_at=now)
        )
        db.commit()

    return {"stale": stale.rowcount, "offline": offline.rowcount}


@celery_app.task(
    name="fleet_platform.workers.maintenance.cleanup_old_bootstrap_runs",
    queue="maintenance",
)
def cleanup_old_bootstrap_runs() -> dict:
    """Delete bootstrap run records older than the configured retention period."""
    with get_sync_db() as db:
        row = db.execute(
            select(PlatformSetting).where(
                PlatformSetting.key == "bootstrap_log_retention_days"
            )
        ).scalar_one_or_none()
        days = int(row.value) if row and row.value else 30
        cutoff = datetime.now(UTC) - timedelta(days=days)

        runs = db.execute(
            select(BootstrapRun).where(BootstrapRun.finished_at < cutoff)
        ).scalars().all()
        count = len(runs)
        for run in runs:
            db.delete(run)
        db.commit()

    return {"deleted": count, "cutoff_days": days}
