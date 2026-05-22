from celery import Celery
from celery.schedules import crontab

from fleet_platform.core.config import settings

celery_app = Celery(
    "fleet_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "fleet_platform.workers.drift_tasks",
        "fleet_platform.workers.sbom_tasks",
        "fleet_platform.workers.maintenance",
        "fleet_platform.workers.ansible_tasks",
        "fleet_platform.workers.playbook_tasks",
        "fleet_platform.workers.security_tasks",
        "fleet_platform.workers.salt_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "fleet_platform.workers.drift_tasks.*": {"queue": "drift"},
        "fleet_platform.workers.sbom_tasks.*": {"queue": "sbom"},
        "fleet_platform.workers.maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "mark-stale-nodes": {
            "task": "fleet_platform.workers.maintenance.mark_stale_nodes",
            "schedule": 300,
        },
        "archive-old-sbom-scans": {
            "task": "fleet_platform.workers.sbom_tasks.cleanup_old_sbom_scans",
            "schedule": crontab(hour=2, minute=0),
            "kwargs": {"keep_count": 3},
        },
        "cleanup-old-bootstrap-runs": {
            "task": "fleet_platform.workers.maintenance.cleanup_old_bootstrap_runs",
            "schedule": crontab(hour=3, minute=0),
        },
        "refresh-all-node-grains": {
            "task": "fleet_platform.workers.ansible_tasks.refresh_all_node_grains",
            "schedule": crontab(hour="*/6", minute=0),
        },
    },
)
