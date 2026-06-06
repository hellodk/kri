"""Tests for playbook log flush interval and elapsed time (#298)."""


def test_log_flush_interval_is_5_seconds():
    """_LOG_BATCH_INTERVAL must be 5 seconds for responsive log updates."""
    from fleet_platform.workers.playbook_tasks import _LOG_BATCH_INTERVAL

    assert _LOG_BATCH_INTERVAL == 5, (
        f"_LOG_BATCH_INTERVAL is {_LOG_BATCH_INTERVAL}s — must be 5s for operators "
        "to see progress during long tasks. Was 30s which caused 30s+ blind spots."
    )


def test_playbook_job_detail_shows_elapsed_time():
    content = open("frontend/src/pages/PlaybookJobDetail.tsx").read()
    assert "elapsed" in content
    assert "fmtElapsed" in content or "elapsed" in content


def test_playbook_job_detail_shows_current_task():
    content = open("frontend/src/pages/PlaybookJobDetail.tsx").read()
    assert "running:" in content
