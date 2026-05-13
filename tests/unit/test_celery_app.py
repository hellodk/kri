from fleet_platform.workers.celery_app import celery_app


def test_celery_app_is_configured():
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.enable_utc is True


def test_celery_queues_defined():
    routes = celery_app.conf.task_routes
    assert any("drift_tasks" in k for k in routes)
    assert any("sbom_tasks" in k for k in routes)
    assert any("maintenance" in k for k in routes)


def test_beat_schedule_has_mark_stale_nodes():
    schedule = celery_app.conf.beat_schedule
    assert "mark-stale-nodes" in schedule
    assert schedule["mark-stale-nodes"]["schedule"] == 300
