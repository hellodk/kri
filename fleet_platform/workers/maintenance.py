from datetime import UTC, datetime, timedelta

import redis as sync_redis
from sqlalchemy import select, update

from fleet_platform.core.config import settings
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.bootstrap_run import BootstrapRun
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.services.platform_settings_svc import (
    NODE_OFFLINE_THRESHOLD_HOURS,
    NODE_STALE_THRESHOLD_MINUTES,
    get_setting_sync,
)
from fleet_platform.workers.celery_app import celery_app

# H-4 fix (SRE audit): dead-man's-switch key. Updated every time mark_stale_nodes
# runs successfully. Monitoring endpoint reads this to detect a stuck beat worker.
_MAINTENANCE_HEARTBEAT_KEY = "kri:maintenance:last_run"
_MAINTENANCE_HEARTBEAT_TTL = 600  # 10 min — expires if beat dies

_DEFAULT_STALE_MINUTES = 15  # 3 missed heartbeats
_DEFAULT_OFFLINE_HOURS = 4  # raised from 1h — 1h caused false-offline during kri maintenance


@celery_app.task(name="fleet_platform.workers.maintenance.mark_stale_nodes")
def mark_stale_nodes() -> dict:
    """Mark nodes as stale or offline based on last_seen_at. Runs every 5 minutes via beat."""
    now = datetime.now(UTC)

    with get_sync_db() as db:
        # Read thresholds from platform settings; fall back to defaults on missing/invalid values
        try:
            stale_minutes = int(get_setting_sync(db, NODE_STALE_THRESHOLD_MINUTES) or _DEFAULT_STALE_MINUTES)
        except (TypeError, ValueError):
            stale_minutes = _DEFAULT_STALE_MINUTES

        try:
            offline_hours = int(get_setting_sync(db, NODE_OFFLINE_THRESHOLD_HOURS) or _DEFAULT_OFFLINE_HOURS)
        except (TypeError, ValueError):
            offline_hours = _DEFAULT_OFFLINE_HOURS

        stale_cutoff = now - timedelta(minutes=stale_minutes)
        offline_cutoff = now - timedelta(hours=offline_hours)
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

    # H-4: Update dead-man's-switch — monitoring reads this to detect a hung beat worker
    try:
        r = sync_redis.Redis.from_url(settings.redis_url)
        r.setex(_MAINTENANCE_HEARTBEAT_KEY, _MAINTENANCE_HEARTBEAT_TTL, now.isoformat())
    except Exception:
        pass  # Redis unavailable — don't fail the task, just skip the heartbeat

    return {"stale": stale.rowcount, "offline": offline.rowcount}  # type: ignore[attr-defined]


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


_ORPHAN_TIMEOUT_MINUTES = 40  # hard kill limit is 35 min; give 5 min buffer


@celery_app.task(
    name="fleet_platform.workers.maintenance.reap_orphaned_jobs",
    queue="maintenance",
)
def reap_orphaned_jobs() -> dict:
    """Mark ansible_jobs stuck in 'running' as failed if the worker was restarted.

    Celery SoftTimeLimitExceeded only fires in a living worker. When a worker
    is restarted mid-task, the DB row stays 'running' forever. This reaper runs
    every 15 minutes and marks any job that has been 'running' for longer than
    the Celery hard time limit (35 min) as failed with a clear explanation.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=_ORPHAN_TIMEOUT_MINUTES)
    with get_sync_db() as db:
        result = db.execute(
            update(AnsibleJob)
            .where(AnsibleJob.status == "running")
            .where(AnsibleJob.started_at < cutoff)
            .values(
                status="failed",
                completed_at=datetime.now(UTC),
                stdout=(
                    "[ERROR] Task orphaned — the Celery worker was restarted while this job "
                    "was running. The playbook may or may not have executed on the target. "
                    "Check the node directly and re-run the playbook if needed."
                ),
            )
        )
        db.commit()
    return {"reaped": result.rowcount}
