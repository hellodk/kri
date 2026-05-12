from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.index_sbom",
    bind=True,
    max_retries=3,
    queue="sbom",
)
def index_sbom(self, node_id: str, file_path: str) -> dict:
    """Index SBOM components from a CycloneDX file. Full implementation in Plan 5."""
    return {"node_id": node_id, "status": "queued", "file_path": file_path}
