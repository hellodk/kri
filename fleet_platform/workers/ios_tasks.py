"""Celery tasks for iOS fleet tracking."""
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.ios_tasks.check_all_jenkins_agents",
    queue="maintenance",
)
def check_all_jenkins_agents():
    import asyncio

    from sqlalchemy import select

    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.models.ios_tracking import JenkinsAgent
    from fleet_platform.services.ios_tracking_svc import check_jenkins_agent

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(JenkinsAgent))
            agents = result.scalars().all()
            for agent in agents:
                await check_jenkins_agent(agent.id, db)

    asyncio.run(_run())
