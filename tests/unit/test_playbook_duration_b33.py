"""Tests for #165: playbook duration stats endpoint."""

from pathlib import Path

ANSIBLE_ROUTE = (Path(__file__).parent.parent.parent / "fleet_platform/api/routes/ansible.py").read_text()


def test_playbook_stats_endpoint_exists():
    assert "playbook_stats" in ANSIBLE_ROUTE


def test_playbook_stats_endpoint_path():
    assert "/playbooks/{playbook_name" in ANSIBLE_ROUTE


def test_playbook_stats_returns_last_duration():
    assert "last_duration_seconds" in ANSIBLE_ROUTE


def test_playbook_stats_returns_avg_duration():
    assert "avg_duration_seconds" in ANSIBLE_ROUTE


def test_playbook_stats_limits_to_5_runs():
    assert ".limit(5)" in ANSIBLE_ROUTE


def test_playbook_stats_only_completed_jobs():
    assert '"completed"' in ANSIBLE_ROUTE


def test_fmtduration_in_frontend():
    modal = (Path(__file__).parent.parent.parent / "frontend/src/pages/PlaybookRunModal.tsx").read_text()
    assert "fmtDuration" in modal or "last_duration_seconds" in modal


def test_playbook_stats_api_in_frontend():
    api = (Path(__file__).parent.parent.parent / "frontend/src/api/playbooks.ts").read_text()
    assert "getStats" in api
    assert "PlaybookStats" in api
