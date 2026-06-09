import asyncio
from datetime import UTC, datetime, timedelta

import redis as sync_redis
from sqlalchemy import String, and_, cast, delete, func, or_, select, update

from fleet_platform.core.config import settings
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.bootstrap_run import BootstrapRun
from fleet_platform.models.master_provision_run import MasterProvisionRun
from fleet_platform.models.node import Node
from fleet_platform.models.pending_action import PendingAction
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.platform_settings_svc import (
    NODE_OFFLINE_THRESHOLD_HOURS,
    NODE_STALE_THRESHOLD_MINUTES,
    get_setting_sync,
)
from fleet_platform.services.salt_master_probe import run_probe
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
            .where(Node.maintenance_mode.is_(False))  # #456: skip nodes in maintenance mode
            .values(status="stale", updated_at=now)
        )
        offline = db.execute(
            update(Node)
            .where(Node.last_seen_at < offline_cutoff)
            .where(Node.status.in_(["online", "stale"]))
            .where(Node.maintenance_mode.is_(False))  # #456: skip nodes in maintenance mode
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
    """Delete bootstrap run records older than the configured retention period.

    Also deletes NULL finished_at rows that are stuck in non-running states (#445 Part B).
    """
    with get_sync_db() as db:
        row = db.execute(
            select(PlatformSetting).where(PlatformSetting.key == "bootstrap_log_retention_days")
        ).scalar_one_or_none()
        days = int(row.value) if row and row.value else 30
        cutoff = datetime.now(UTC) - timedelta(days=days)

        result = db.execute(
            delete(BootstrapRun).where(
                or_(
                    BootstrapRun.finished_at < cutoff,
                    and_(
                        BootstrapRun.finished_at.is_(None),
                        BootstrapRun.status != "running",
                        BootstrapRun.started_at < cutoff,
                    ),
                )
            )
        )
        db.commit()
        count = result.rowcount  # type: ignore[attr-defined]

    return {"deleted": count, "cutoff_days": days}


# #352: per-job orphan buffer — a running job is considered orphaned when
# started_at < now() - (job.timeout_seconds + _ORPHAN_BUFFER_SECONDS).
# The static _ORPHAN_TIMEOUT_MINUTES was removed; #348 introduced per-job
# timeout_seconds so a single global cutoff was always wrong.
_ORPHAN_BUFFER_SECONDS = 300  # 5-min grace period on top of job's own timeout

_ORPHAN_MESSAGE = (
    "\n\n[ERROR] Task orphaned — the Celery worker was restarted while this job "
    "was running. The playbook may or may not have executed on the target. "
    "Check the node directly and re-run the playbook if needed."
)


@celery_app.task(
    name="fleet_platform.workers.maintenance.reap_orphaned_jobs",
    queue="maintenance",
)
def reap_orphaned_jobs() -> dict:
    """Mark ansible_jobs stuck in 'running' as failed if the worker was restarted.

    Cutoff is per-job: a job is orphaned when
        started_at < now() - (job.timeout_seconds + _ORPHAN_BUFFER_SECONDS)
    so a short job (timeout=120s) is reaped after 420s while a long job
    (timeout=3600s) is only reaped after 3900s. (#348/#352)

    Guards:
    - completed_at IS NULL: skip jobs that finished legitimately (race guard, closes #305)
    - started_at IS NULL fallback via created_at: catches permanent orphans
    - func.coalesce: append to existing stdout instead of overwriting evidence
    """
    now = datetime.now(UTC)
    with get_sync_db() as db:
        result = db.execute(
            update(AnsibleJob)
            .where(AnsibleJob.status == "running")
            .where(AnsibleJob.completed_at.is_(None))
            .where(
                or_(
                    AnsibleJob.started_at
                    < func.now()
                    - func.make_interval(0, 0, 0, 0, 0, 0, AnsibleJob.timeout_seconds + _ORPHAN_BUFFER_SECONDS),
                    AnsibleJob.started_at.is_(None)
                    & (
                        AnsibleJob.created_at
                        < func.now()
                        - func.make_interval(0, 0, 0, 0, 0, 0, AnsibleJob.timeout_seconds + _ORPHAN_BUFFER_SECONDS)
                    ),
                )
            )
            .values(
                status="failed",
                completed_at=now,
                stdout=func.concat(func.coalesce(cast(AnsibleJob.stdout, String), ""), _ORPHAN_MESSAGE),
            )
        )
        db.commit()
    return {"reaped": result.rowcount}  # type: ignore[attr-defined]


# #519: backoff for unreachable masters — probe at most once every 5 minutes
# rather than every 30 s (the beat interval).  This avoids hammering a downed
# master on every tick while still recovering quickly once it comes back.
_SALT_UNREACHABLE_BACKOFF_SECONDS = 300

# Dead-man's-switch key for salt-master polling.  Expires after 120 s;
# monitoring alerts if this key disappears (beat stuck / worker down).
_SALT_POLL_HEARTBEAT_KEY = "kri:salt:poll:last_run"
_SALT_POLL_HEARTBEAT_TTL = 120

_BOOTSTRAP_ORPHAN_MINUTES = 90  # bootstraps taking longer than 90 min are orphaned


@celery_app.task(
    name="fleet_platform.workers.maintenance.reap_orphaned_bootstraps",
    queue="maintenance",
)
def reap_orphaned_bootstraps() -> dict:
    """Mark BootstrapRun rows stuck in 'running' as failed (#445 Part C).

    A bootstrap is considered orphaned when it has been running for longer than
    _BOOTSTRAP_ORPHAN_MINUTES — the worker was likely restarted mid-run.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=_BOOTSTRAP_ORPHAN_MINUTES)
    with get_sync_db() as db:
        stuck_node_ids = (
            db.execute(
                select(BootstrapRun.node_id)
                .where(BootstrapRun.status == "running")
                .where(BootstrapRun.started_at < cutoff)
            )
            .scalars()
            .all()
        )

        result = db.execute(
            update(BootstrapRun)
            .where(BootstrapRun.status == "running")
            .where(BootstrapRun.started_at < cutoff)
            .values(status="failed", finished_at=now)
        )

        if stuck_node_ids:
            db.execute(
                update(Node)
                .where(Node.id.in_(stuck_node_ids))
                .where(Node.bootstrap_status == "bootstrapping")
                .values(bootstrap_status="failed")
            )

        db.commit()
    return {"reaped": result.rowcount}  # type: ignore[attr-defined]


@celery_app.task(
    name="fleet_platform.workers.maintenance.poll_salt_masters",
    queue="maintenance",
)
def poll_salt_masters() -> dict:
    """Poll every enabled SaltMaster and cache the probe result in the DB row.

    Runs every 30 s via beat.  The web app reads the cached ``status`` /
    ``checks`` / ``last_checked_at`` fields instead of ever making a live
    salt-api call during request handling.

    Backoff: if a master is currently ``unreachable`` and was checked within
    the last ``_SALT_UNREACHABLE_BACKOFF_SECONDS`` seconds, it is skipped this
    tick.  This avoids hammering a down master every 30 s while still recovering
    quickly once the master comes back (it will be retried within
    ``_SALT_UNREACHABLE_BACKOFF_SECONDS`` seconds of the last check).

    A master with ``last_checked_at=None`` (never probed) is always polled,
    regardless of its current ``status``.

    A dead-man's-switch key (``kri:salt:poll:last_run``) is refreshed in Redis
    at the end of every successful run.  Monitoring alerts if the key expires.
    Redis failures are swallowed so they never abort the task.
    """
    now = datetime.now(UTC)
    polled = 0
    skipped = 0

    with get_sync_db() as db:
        masters = db.execute(select(SaltMaster).where(SaltMaster.enabled.is_(True))).scalars().all()

        for master in masters:
            # Backoff: skip recently-checked unreachable masters
            if master.status == "unreachable" and master.last_checked_at is not None:
                age = (now - master.last_checked_at).total_seconds()
                if age < _SALT_UNREACHABLE_BACKOFF_SECONDS:
                    skipped += 1
                    continue

            result = asyncio.run(run_probe(master))

            master.status = result["status"]
            master.checks = result["checks"]  # type: ignore[assignment]
            master.last_checked_at = datetime.now(UTC)

            failed_checks = [c for c in result["checks"] if c.get("status") == "fail"]
            master.last_error = failed_checks[0]["detail"] if failed_checks else None

            polled += 1

        db.commit()

    # Dead-man's-switch — Redis down must never fail this task
    try:
        r = sync_redis.Redis.from_url(settings.redis_url)
        r.setex(_SALT_POLL_HEARTBEAT_KEY, _SALT_POLL_HEARTBEAT_TTL, datetime.now(UTC).isoformat())
    except Exception:
        pass

    return {"polled": polled, "skipped": skipped}


# #640: actions are stuck 'executing' when finalize_node_action was routed to the
# unmonitored 'celery' queue.  This reaper catches any that slipped through (e.g.
# during the window before the deploy, or if the callback was lost for any reason).
_EXECUTING_ORPHAN_MINUTES = 10  # action still 'executing' after 10 min → failed


@celery_app.task(
    name="fleet_platform.workers.maintenance.reap_stuck_pending_actions",
    queue="maintenance",
)
def reap_stuck_pending_actions() -> dict:
    """Reap PendingAction rows stuck in transient states (#640).

    Two passes:
    1. 'executing' rows whose executed_at is older than _EXECUTING_ORPHAN_MINUTES
       are marked 'failed' — the finalize callback never arrived (or was lost on
       the unmonitored queue before the fix was deployed).
    2. 'pending' rows whose expires_at has passed are marked 'expired' — mirrors
       the async expire_old() in pending_action_svc but runs synchronously on the
       beat worker so it executes without a live API request.
    """
    now = datetime.now(UTC)
    executing_cutoff = now - timedelta(minutes=_EXECUTING_ORPHAN_MINUTES)

    with get_sync_db() as db:
        reaped = db.execute(
            update(PendingAction)
            .where(PendingAction.status == "executing")
            .where(PendingAction.executed_at < executing_cutoff)
            .values(status="failed")
        )

        expired = db.execute(
            update(PendingAction)
            .where(PendingAction.status == "pending")
            .where(PendingAction.expires_at < now)
            .values(status="expired")
        )

        db.commit()

    return {
        "reaped_executing": reaped.rowcount,  # type: ignore[attr-defined]
        "expired_pending": expired.rowcount,  # type: ignore[attr-defined]
    }


_PROVISION_ORPHAN_MINUTES = 90  # provisions running > 90 min are considered orphaned


@celery_app.task(
    name="fleet_platform.workers.maintenance.reap_orphaned_master_provisions",
    queue="maintenance",
)
def reap_orphaned_master_provisions() -> dict:
    """Mark MasterProvisionRun rows stuck in 'running' as failed (#557).

    Mirrors reap_orphaned_bootstraps.  Any provision that has been running
    longer than _PROVISION_ORPHAN_MINUTES is considered orphaned (worker restart
    mid-run).  The owning SaltMaster.provision_status is flipped to 'failed' if
    it is still 'provisioning'.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=_PROVISION_ORPHAN_MINUTES)

    with get_sync_db() as db:
        # Collect master IDs for orphaned runs before bulk-updating them
        stuck_master_ids = (
            db.execute(
                select(MasterProvisionRun.salt_master_id)
                .where(MasterProvisionRun.status == "running")
                .where(MasterProvisionRun.started_at < cutoff)
            )
            .scalars()
            .all()
        )

        result = db.execute(
            update(MasterProvisionRun)
            .where(MasterProvisionRun.status == "running")
            .where(MasterProvisionRun.started_at < cutoff)
            .values(status="failed", finished_at=now)
        )

        if stuck_master_ids:
            db.execute(
                update(SaltMaster)
                .where(SaltMaster.id.in_(stuck_master_ids))
                .where(SaltMaster.provision_status == "provisioning")
                .values(provision_status="failed")
            )

        db.commit()

    return {"reaped": result.rowcount}  # type: ignore[attr-defined]
