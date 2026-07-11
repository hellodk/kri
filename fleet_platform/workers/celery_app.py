from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from fleet_platform.core.config import settings


@worker_process_init.connect
def _init_worker_observability(**_kwargs) -> None:
    """Initialise structured logging and OpenTelemetry once per worker process.

    Celery prefork creates one process per concurrency slot; both structlog
    and the OTEL SDK store state in module globals that must live in each
    child, not the parent. ``worker_process_init`` is the standard hook.

    Without ``configure_logging()`` here, worker stdout would be plain stdlib
    text rather than the JSON-with-trace_id format that the API emits — the
    OTEL backend can still join records by trace_id, but Loki/Promtail can't.
    """
    from fleet_platform.core.logging import configure_logging
    from fleet_platform.core.tracing import (
        configure_tracing,
        instrument_celery,
        instrument_httpx,
        instrument_redis,
        instrument_sqlalchemy,
    )

    configure_logging()
    configure_tracing(service_name="kri-worker")
    instrument_celery()
    instrument_sqlalchemy()
    instrument_httpx()
    instrument_redis()


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
        "fleet_platform.workers.salt_presence_tasks",
        "fleet_platform.workers.alert_tasks",
        "fleet_platform.workers.ios_tasks",
        "fleet_platform.workers.health_tasks",
        "fleet_platform.workers.digest_tasks",
        "fleet_platform.workers.embedding_tasks",
        "fleet_platform.workers.mobileconfig_tasks",
        "fleet_platform.workers.connectivity_tasks",
        "fleet_platform.workers.fleet_recommendations_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # ── Celery Beat HA via RedBeat (#754 — ARC-10) ───────────────────────────
    # RedBeat stores the beat schedule and a heartbeat key in Redis so that
    # multiple beat processes can safely compete for leadership. Only one
    # instance holds the schedule lock at a time; if it crashes, a standby
    # picks up within one schedule interval (typically ≤ 30 s for the fastest
    # task here). This eliminates the "silent SPOF" where a single beat crash
    # stops grain refresh, alert evaluation, and all reapers with no alert.
    #
    # Operational notes (CODE change — see also DEPLOY note below):
    #   • ``beat_scheduler`` replaces the default PersistentScheduler. A
    #     ``celerybeat-schedule`` file is no longer used.
    #   • ``redbeat_redis_url`` must point at the same Redis instance as the
    #     broker so the lock and the broker share a connection pool.
    #   • ``redbeat_lock_timeout`` defaults to 5 × the shortest schedule
    #     interval; override if needed (e.g. ``redbeat_lock_timeout=150``).
    #
    # DEPLOY note (operational, not code):
    #   • Run two beat replicas: ``celery -A fleet_platform.workers.celery_app
    #     beat -S redbeat.RedBeatScheduler --loglevel=info``.
    #   • The second replica is a hot-standby and takes over within one lock-
    #     timeout (≈ 150 s at the 30-s ``poll-salt-masters`` schedule) if the
    #     primary dies. No other config change is needed.
    #   • In Kubernetes: set ``replicas: 2`` on the beat Deployment; RedBeat
    #     handles the election. Do NOT use a StatefulSet or single-replica
    #     Deployment for beat if HA is desired.
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=settings.redis_url,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=1800,  # 30 min soft limit — raises SoftTimeLimitExceeded
    task_time_limit=2100,  # 35 min hard kill — SIGKILL if soft limit is ignored
    task_routes={
        "fleet_platform.workers.drift_tasks.*": {"queue": "drift"},
        "fleet_platform.workers.sbom_tasks.*": {"queue": "sbom"},
        "fleet_platform.workers.maintenance.*": {"queue": "maintenance"},
        "fleet_platform.workers.health_tasks.*": {"queue": "maintenance"},
        # RAG reindex tasks must land on a worker-consumed queue (#573). Without
        # this they fell through to the default "celery" queue, which the worker
        # (--queues default,maintenance,drift,sbom) never consumes → embeddings
        # were never (re)built.
        "fleet_platform.workers.embedding_tasks.*": {"queue": "maintenance"},
        # Long-running ansible jobs (#579) get a DEDICATED queue, consumed by a
        # separate worker, so a burst of 2h playbook/bootstrap/provision runs can
        # never starve the fast control-plane "maintenance" queue (poll_salt_masters,
        # presence sync, reapers, health). Routed by exact task name — the other
        # tasks in these modules (collect_node_grains, refresh_all_node_grains)
        # stay on the control-plane queue. The decorator queue= on each task is
        # also "ansible" so apply_async options can't override this back.
        "fleet_platform.workers.playbook_tasks.run_playbook": {"queue": "ansible"},
        "fleet_platform.workers.ansible_tasks.bootstrap_node": {"queue": "ansible"},
        "fleet_platform.workers.ansible_tasks.provision_master": {"queue": "ansible"},
    },
    beat_schedule={
        "mark-stale-nodes": {
            "task": "fleet_platform.workers.maintenance.mark_stale_nodes",
            "schedule": 300,
        },
        "sync-minion-presence": {
            "task": "fleet_platform.workers.salt_presence_tasks.sync_minion_presence",
            "schedule": 90,  # every 90s — nodes appear online within 90s of minion connect
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
        "cleanup-old-llm-logs": {
            "task": "fleet_platform.workers.maintenance.cleanup_old_llm_logs",
            "schedule": crontab(hour=4, minute=0),  # daily 04:00 UTC
            "options": {"queue": "maintenance"},
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
        "reap-orphaned-jobs": {
            "task": "fleet_platform.workers.maintenance.reap_orphaned_jobs",
            "schedule": 300,  # every 5 minutes — worst-case stale-running window (#352)
        },
        "reap-orphaned-bootstraps": {
            "task": "fleet_platform.workers.maintenance.reap_orphaned_bootstraps",
            "schedule": crontab(minute="*/30"),  # every 30 minutes (#445)
        },
        "reap-orphaned-master-provisions": {
            "task": "fleet_platform.workers.maintenance.reap_orphaned_master_provisions",
            "schedule": crontab(minute="*/30"),  # every 30 minutes — mirrors bootstrap reaper (#557)
            "options": {"queue": "maintenance"},
        },
        "reindex-nodes": {
            "task": "fleet_platform.workers.embedding_tasks.reindex_nodes",
            "schedule": 300,  # every 5 min — tracks node status changes
        },
        "reindex-playbooks": {
            "task": "fleet_platform.workers.embedding_tasks.reindex_playbooks",
            "schedule": 900,  # every 15 min — tracks playbook file changes
        },
        "reindex-drift-history": {
            "task": "fleet_platform.workers.embedding_tasks.reindex_drift_history",
            "schedule": 300,  # every 5 min — tracks new drift records
        },
        "check-ssh-connectivity": {
            "task": "fleet_platform.workers.connectivity_tasks.check_ssh_connectivity",
            "schedule": 900,  # every 15 minutes — proactive SSH reachability sweep (#356)
            "options": {"queue": "maintenance"},
        },
        "poll-salt-masters": {
            "task": "fleet_platform.workers.maintenance.poll_salt_masters",
            "schedule": 30,  # every 30 s — keeps UI health cache fresh (#519)
            "options": {"queue": "maintenance"},
        },
        # #640: reap pending-actions stuck in 'executing' (callback lost on the
        # unmonitored 'celery' queue) and expire stale 'pending' rows.
        "reap-stuck-pending-actions": {
            "task": "fleet_platform.workers.maintenance.reap_stuck_pending_actions",
            "schedule": 300,  # every 5 min
            "options": {"queue": "maintenance"},
        },
        "sweep-agent-quarantine": {
            "task": "fleet_platform.workers.maintenance.sweep_agent_quarantine",
            "schedule": crontab(minute=15),  # hourly — TTL is 24h, so hourly is ample (#713)
            "options": {"queue": "maintenance"},
        },
        "generate-fleet-recommendations": {
            "task": "fleet_platform.workers.fleet_recommendations_tasks.generate_fleet_recommendations",
            "schedule": crontab(hour=6, minute=0),  # daily 06:00 UTC (#4)
            "options": {"queue": "maintenance"},
        },
    },
)
