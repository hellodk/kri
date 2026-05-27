from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_db(builds=None, total_nodes=5, online_nodes=3):
    """Build a mock sync SQLAlchemy Session returning test data."""
    db = MagicMock()

    build_list = builds or []

    call_count = {"n": 0}

    def execute_side_effect(stmt):
        call_count["n"] += 1
        mock_result = MagicMock()

        # First call: builds query
        if call_count["n"] == 1:
            mock_result.scalars.return_value.all.return_value = build_list
        # Second call: total_nodes count
        elif call_count["n"] == 2:
            mock_result.scalar_one.return_value = total_nodes
        # Third call: online_nodes count
        else:
            mock_result.scalar_one.return_value = online_nodes

        return mock_result

    db.execute.side_effect = execute_side_effect
    return db


def _make_build(job_name="test-job", build_number=1, result="SUCCESS"):
    mock = MagicMock()
    mock.job_name = job_name
    mock.build_number = build_number
    mock.result = result
    mock.started_at = datetime.now(UTC)
    return mock


def test_get_week_stats_empty_builds():
    from fleet_platform.services.digest_svc import get_week_stats

    db = _make_db(builds=[], total_nodes=10, online_nodes=7)
    stats = get_week_stats(db)

    assert stats["builds_total"] == 0
    assert stats["builds_passed"] == 0
    assert stats["builds_failed"] == 0
    assert stats["top_failing_jobs"] == []
    assert stats["total_nodes"] == 10
    assert stats["online_nodes"] == 7


def test_get_week_stats_counts_failures():
    from fleet_platform.services.digest_svc import get_week_stats

    builds = [
        _make_build("job-a", 1, "SUCCESS"),
        _make_build("job-a", 2, "FAILURE"),
        _make_build("job-a", 3, "FAILURE"),
        _make_build("job-b", 1, "FAILURE"),
        _make_build("job-b", 2, "SUCCESS"),
    ]
    db = _make_db(builds=builds)
    stats = get_week_stats(db)

    assert stats["builds_total"] == 5
    assert stats["builds_passed"] == 2
    assert stats["builds_failed"] == 3
    # job-a has 2 failures, job-b has 1 — job-a should be first
    assert stats["top_failing_jobs"][0] == ("job-a", 2)
    assert stats["top_failing_jobs"][1] == ("job-b", 1)


def test_get_week_stats_unstable_counts_as_failed():
    from fleet_platform.services.digest_svc import get_week_stats

    builds = [_make_build("job-x", 1, "UNSTABLE")]
    db = _make_db(builds=builds)
    stats = get_week_stats(db)

    assert stats["builds_failed"] == 1
    assert stats["top_failing_jobs"][0][0] == "job-x"


def test_render_html_contains_stats():
    from fleet_platform.services.digest_svc import render_html

    stats = {
        "builds_total": 42,
        "builds_passed": 38,
        "builds_failed": 4,
        "top_failing_jobs": [("deploy-prod", 3), ("ci-lint", 1)],
        "total_nodes": 20,
        "online_nodes": 18,
        "period_start": "2026-05-20",
        "period_end": "2026-05-27",
    }
    html = render_html(stats)

    assert "42" in html
    assert "38" in html
    assert "4" in html
    assert "deploy-prod" in html
    assert "20" in html
    assert "18" in html
    assert "90%" in html  # pass rate: 38/42 = ~90%


def test_render_html_no_failures():
    from fleet_platform.services.digest_svc import render_html

    stats = {
        "builds_total": 10,
        "builds_passed": 10,
        "builds_failed": 0,
        "top_failing_jobs": [],
        "total_nodes": 5,
        "online_nodes": 5,
        "period_start": "2026-05-20",
        "period_end": "2026-05-27",
    }
    html = render_html(stats)
    assert "No failures" in html


def test_send_digest_raises_when_smtp_not_configured():
    from fleet_platform.services.digest_svc import send_digest

    db = MagicMock()
    with patch("fleet_platform.services.digest_svc.get_setting_sync", return_value=None):
        with pytest.raises(ValueError, match="SMTP host not configured"):
            send_digest(db)


def test_send_digest_raises_when_no_recipients():
    from fleet_platform.services.digest_svc import send_digest

    def mock_get_setting(db, key):
        if key == "smtp_host":
            return "smtp.example.com"
        if key == "digest_recipients":
            return ""
        return None

    with patch("fleet_platform.services.digest_svc.get_setting_sync", side_effect=mock_get_setting):
        with pytest.raises(ValueError, match="No digest recipients"):
            send_digest(MagicMock())


def test_get_setting_sync_returns_none_when_missing():
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = get_setting_sync(mock_db, "nonexistent_key")
    assert result is None


def test_get_setting_sync_returns_plaintext():
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.services.platform_settings_svc import get_setting_sync

    row = MagicMock(spec=PlatformSetting)
    row.is_encrypted = False
    row.value = "smtp.example.com"

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = row

    result = get_setting_sync(mock_db, "smtp_host")
    assert result == "smtp.example.com"
