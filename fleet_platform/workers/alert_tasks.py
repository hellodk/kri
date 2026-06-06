"""Celery tasks for alert evaluation."""

import asyncio

from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.alert_tasks.run_alert_evaluation",
    queue="maintenance",
)
def run_alert_evaluation():
    """Evaluate all alert rules.

    Uses asyncio.new_event_loop() — creates an isolated loop owned by this
    invocation. Safe for prefork Celery workers. Not compatible with gevent/eventlet;
    if the pool is changed, refactor to use asgiref.sync.async_to_sync.
    """
    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.services.alert_svc import evaluate_alerts

    loop = asyncio.new_event_loop()
    try:

        async def _run():
            async with AsyncSessionLocal() as db:
                await evaluate_alerts(db)

        loop.run_until_complete(_run())
    finally:
        loop.close()
