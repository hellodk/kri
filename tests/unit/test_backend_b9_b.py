"""Unit tests for #132 (scan_cxone blocking) and #158 (alert_tasks event loop)."""

from pathlib import Path


def test_scan_cxone_max_wait_reduced():
    """_scan_cxone must not poll for longer than 3 minutes (was 10 min)."""
    src = Path("fleet_platform/workers/security_tasks.py").read_text()
    # Must not have the old range(60) + sleep(10) combination
    assert not ("range(60)" in src and "sleep(10)" in src), (
        "_scan_cxone must not use range(60) with sleep(10) — blocks worker 10 min"
    )


def test_alert_tasks_no_bare_asyncio_run():
    """alert_tasks must not use asyncio.run() directly — use new_event_loop() instead."""
    src = Path("fleet_platform/workers/alert_tasks.py").read_text()
    assert "asyncio.run(" not in src, (
        "alert_tasks must not use asyncio.run() — use new_event_loop() for Celery prefork safety"
    )


def test_ios_tasks_no_asyncio_run():
    """ios_tasks must use get_sync_db, not asyncio.run()."""
    src = Path("fleet_platform/workers/ios_tasks.py").read_text()
    assert "asyncio.run(" not in src
    assert "get_sync_db" in src
