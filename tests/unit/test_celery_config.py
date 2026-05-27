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
    """Fix #112 — check_all_jenkins_agents must not import asyncio.run at module level."""
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


def test_playbook_task_has_timeout():
    """Fix #129 — run_playbook ansible_runner call must include timeout=1200."""
    import ast
    import inspect

    from fleet_platform.workers import playbook_tasks

    source = inspect.getsource(playbook_tasks)
    tree = ast.parse(source)

    timeout_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Look for ansible_runner.run(...)
            if isinstance(func, ast.Attribute) and func.attr == "run":
                for kw in node.keywords:
                    if kw.arg == "timeout":
                        if isinstance(kw.value, ast.Constant) and kw.value.value == 1200:
                            timeout_found = True

    assert timeout_found, (
        "ansible_runner.run() in playbook_tasks must include timeout=1200"
    )
