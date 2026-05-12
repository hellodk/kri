from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
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
