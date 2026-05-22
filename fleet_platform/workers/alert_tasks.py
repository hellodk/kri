"""Celery tasks for alert evaluation."""
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.alert_tasks.run_alert_evaluation",
    queue="maintenance",
)
def run_alert_evaluation():
    import asyncio
    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.services.alert_svc import evaluate_alerts

    async def _run():
        async with AsyncSessionLocal() as db:
            await evaluate_alerts(db)

    asyncio.run(_run())
