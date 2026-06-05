# fleet_platform/workers/digest_tasks.py
"""Weekly fleet digest email task."""

import logging

from fleet_platform.db.session import get_sync_db
from fleet_platform.services.digest_svc import send_digest
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="fleet_platform.workers.digest_tasks.weekly_digest",
    queue="maintenance",
)
def weekly_digest() -> dict:
    """Send the weekly fleet + Jenkins build digest email.

    Scheduled: every Monday 08:00 UTC via Celery beat.
    Also callable on-demand via POST /api/v1/builds/digest/send-now.
    """
    logger.info("weekly_digest: starting")
    with get_sync_db() as db:
        result = send_digest(db)
    logger.info("weekly_digest: sent to %d recipients", result.get("recipients", 0))
    return result
