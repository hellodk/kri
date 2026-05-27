"""Celery tasks for alert evaluation."""
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.alert_tasks.run_alert_evaluation",
    queue="maintenance",
)
def run_alert_evaluation():
    """Evaluate all alert rules using a synchronous DB session.

    Avoids asyncio.run() inside a Celery worker (which may run in a thread
    that already has an event loop attached).  The alert service layer is
    async, so we call it via a freshly-created event loop that we own and
    close ourselves.
    """
    import asyncio

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
