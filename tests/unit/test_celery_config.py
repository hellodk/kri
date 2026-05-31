"""Unit tests for Celery reliability configuration (issue #95)."""


def test_celery_task_acks_late_enabled():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True, (
        "task_acks_late must be True to prevent silent task loss on worker crash"
    )


def test_celery_task_reject_on_worker_lost():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_reject_on_worker_lost is True, (
        "task_reject_on_worker_lost must be True so tasks are re-queued when worker dies"
    )


def test_celery_soft_time_limit_set():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_soft_time_limit == 1800, (
        "task_soft_time_limit should be 1800 s (30 min) to raise SoftTimeLimitExceeded"
    )


def test_celery_hard_time_limit_set():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_time_limit == 2100, (
        "task_time_limit should be 2100 s (35 min) — hard kill if soft limit is ignored"
    )


def test_celery_hard_limit_greater_than_soft():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit, (
        "Hard time limit must exceed soft time limit"
    )


def test_scan_node_security_has_autoretry():
    """Fix #130 — autoretry_for makes max_retries actually trigger on failure."""
    from fleet_platform.workers.security_tasks import scan_node_security

    assert scan_node_security.autoretry_for == (Exception,), (
        "scan_node_security must autoretry_for=(Exception,) so max_retries triggers"
    )
    assert scan_node_security.max_retries == 2


def test_scan_node_security_retry_backoff():
    from fleet_platform.workers.security_tasks import scan_node_security

    assert scan_node_security.retry_backoff is True
    assert scan_node_security.retry_backoff_max == 300
    assert scan_node_security.retry_jitter is True


def test_ios_tasks_uses_sync_db():
    """Fix #112 — check_all_jenkins_agents must not call asyncio.run()."""
    import ast
    import inspect

    from fleet_platform.workers import ios_tasks

    source = inspect.getsource(ios_tasks)
    tree = ast.parse(source)

    # Ensure asyncio.run is not called anywhere in the module
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                if isinstance(func.value, ast.Name) and func.value.id == "asyncio":
                    raise AssertionError(
                        "ios_tasks must not call asyncio.run() — use get_sync_db() instead"
                    )


def test_alert_tasks_no_asyncio_run_at_top_level():
    """Fix #112 — run_alert_evaluation must not use asyncio.run() (event-loop safe)."""
    import ast
    import inspect

    from fleet_platform.workers import alert_tasks

    source = inspect.getsource(alert_tasks)
    tree = ast.parse(source)

    # asyncio.run() is disallowed; asyncio.new_event_loop() is the approved pattern
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                if isinstance(func.value, ast.Name) and func.value.id == "asyncio":
                    raise AssertionError(
                        "alert_tasks must not call asyncio.run() — "
                        "use asyncio.new_event_loop() + loop.run_until_complete() instead"
                    )


def test_playbook_task_uses_run_async():
    """run_playbook must use ansible_runner.run_async() for real-time log streaming.

    run_async returns a (thread, runner) pair and lets us poll events and flush
    partial stdout to DB every 30s so the UI shows progress before completion.
    Using blocking ansible_runner.run() means stdout is NULL until the entire
    playbook finishes (potentially 20+ minutes with no feedback).
    """
    import inspect

    from fleet_platform.workers import playbook_tasks
    source = inspect.getsource(playbook_tasks)
    assert "run_async" in source, (
        "run_playbook must use ansible_runner.run_async() not ansible_runner.run() "
        "so stdout can be flushed to DB incrementally during the run."
    )


def test_playbook_task_flushes_logs_periodically():
    """run_playbook must write partial stdout to DB at intervals, not only at end."""
    import inspect

    from fleet_platform.workers import playbook_tasks
    source = inspect.getsource(playbook_tasks)
    assert "_LOG_BATCH_INTERVAL" in source, (
        "run_playbook must define _LOG_BATCH_INTERVAL and flush stdout periodically"
    )
    assert "_flush_stdout" in source or "flush_stdout" in source, (
        "run_playbook must call a flush function to write partial logs to DB"
    )


def test_playbook_task_handles_soft_time_limit():
    """run_playbook must catch SoftTimeLimitExceeded and write terminal status to DB."""
    import inspect

    from fleet_platform.workers import playbook_tasks
    source = inspect.getsource(playbook_tasks)
    assert "SoftTimeLimitExceeded" in source, (
        "run_playbook must catch SoftTimeLimitExceeded so jobs don't get stuck in 'running'"
    )
