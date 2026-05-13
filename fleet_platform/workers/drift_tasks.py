from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.drift_tasks.compute_drift",
    bind=True,
    max_retries=3,
    queue="drift",
)
def compute_drift(self, node_id: str) -> dict:
    """Compute drift for a node. Full implementation in Plan 4."""
    return {"node_id": node_id, "status": "queued"}
