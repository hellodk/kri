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
        "fleet_platform.workers.alert_tasks",
        "fleet_platform.workers.ios_tasks",
        "fleet_platform.workers.health_tasks",
        "fleet_platform.workers.digest_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    redbeat_redis_url=settings.redis_url,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=1800,   # 30 min soft limit — raises SoftTimeLimitExceeded
    task_time_limit=2100,        # 35 min hard kill — SIGKILL if soft limit is ignored
    task_routes={
        "fleet_platform.workers.drift_tasks.*": {"queue": "drift"},
        "fleet_platform.workers.sbom_tasks.*": {"queue": "sbom"},
        "fleet_platform.workers.maintenance.*": {"queue": "maintenance"},
        "fleet_platform.workers.health_tasks.*": {"queue": "maintenance"},
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
            "schedule": 300,  # every 5 minutes
        },
        "run-alert-evaluation": {
            "task": "fleet_platform.workers.alert_tasks.run_alert_evaluation",
            "schedule": 300,
        },
        "check-jenkins-agents": {
            "task": "fleet_platform.workers.ios_tasks.check_all_jenkins_agents",
            "schedule": 300,
        },
        "collect-fleet-health": {
            "task": "fleet_platform.workers.health_tasks.collect_fleet_health",
            "schedule": 900.0,  # every 15 minutes
        },
        "cleanup-old-health-snapshots": {
            "task": "fleet_platform.workers.health_tasks.cleanup_old_health_snapshots",
            "schedule": crontab(hour=3, minute=30),  # daily at 03:30 UTC
        },
        "weekly-fleet-digest": {
            "task": "fleet_platform.workers.digest_tasks.weekly_digest",
            "schedule": crontab(hour=8, minute=0, day_of_week=1),  # Monday 08:00 UTC
        },
    },
)
