# fleet_platform/workers/fleet_recommendations_tasks.py
"""Celery task for the daily fleet-wide AI recommendation refresh (#4).

Runs the async ``generate_fleet_recommendations`` service on an asyncio event
loop bridged from a synchronous Celery task (mirrors the pattern used in
``embedding_tasks.py``). Never crashes beat: a missing/disabled LLM endpoint
is a normal "skipped" outcome, not a task failure.
"""

import logging

from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="fleet_platform.workers.fleet_recommendations_tasks.generate_fleet_recommendations",
    queue="maintenance",
)
def generate_fleet_recommendations() -> dict:
    """Generate and persist a fresh fleet-wide recommendation set.

    Scheduled: daily at 06:00 UTC via Celery beat (``generated_by="schedule"``).
    Also callable on-demand via POST /api/v1/recommendations/generate.
    """
    import asyncio

    from fleet_platform.db.session import AsyncSessionLocal as async_session_factory
    from fleet_platform.services.fleet_recommendations_svc import (
        generate_fleet_recommendations as _generate,
    )

    async def _run() -> dict:
        async with async_session_factory() as db:
            recommendation = await _generate(db, generated_by="schedule")
            return {
                "status": "generated",
                "id": str(recommendation.id),
                "node_count": recommendation.node_count,
            }

    from fleet_platform.services.llm_caller import LLMCallError

    try:
        return asyncio.run(_run())
    except ValueError as exc:
        logger.info("generate_fleet_recommendations: skipped — %s", exc)
        return {"status": "skipped", "reason": str(exc)}
    except LLMCallError as exc:
        # Transient LLM outage: log + return cleanly so beat records a normal
        # result rather than a noisy task failure.
        logger.warning("generate_fleet_recommendations: LLM call failed — %s", exc)
        return {"status": "error", "reason": str(exc)}
