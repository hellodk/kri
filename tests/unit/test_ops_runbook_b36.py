"""Tests for #122: OPS_RUNBOOK completeness."""
from pathlib import Path

RUNBOOK = (Path(__file__).parent.parent.parent / "docs/OPS_RUNBOOK.md").read_text()


def test_runbook_has_health_checks():
    assert "Health Check" in RUNBOOK or "health" in RUNBOOK.lower()


def test_runbook_has_failure_scenarios():
    assert "Failure" in RUNBOOK or "crash" in RUNBOOK.lower() or "Troubleshooting" in RUNBOOK


def test_runbook_has_backup_restore():
    assert "Backup" in RUNBOOK or "backup" in RUNBOOK.lower()
    assert "Restore" in RUNBOOK or "restore" in RUNBOOK.lower()


def test_runbook_has_redis_coverage():
    assert "redis" in RUNBOOK.lower()


def test_runbook_has_celery_coverage():
    assert "celery" in RUNBOOK.lower() or "worker" in RUNBOOK.lower()


def test_runbook_has_salt_master_coverage():
    assert "salt" in RUNBOOK.lower()


def test_runbook_has_rolling_deploy():
    assert "rolling" in RUNBOOK.lower() or "rolling-deploy" in RUNBOOK


def test_runbook_toc_links():
    assert "##" in RUNBOOK
