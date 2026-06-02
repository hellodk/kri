"""Tests for cancel button UI (#342)."""


def test_playbook_job_detail_has_cancel_button():
    content = open("frontend/src/pages/PlaybookJobDetail.tsx").read()
    assert "cancelMutation" in content
    assert "Cancel" in content
    assert "playbooksApi.cancel" in content


def test_playbooksapi_has_cancel_method():
    content = open("frontend/src/api/playbooks.ts").read()
    assert "cancel:" in content
    assert "/cancel" in content


def test_cancelled_status_styled_in_job_detail():
    content = open("frontend/src/pages/PlaybookJobDetail.tsx").read()
    assert "cancelled" in content.lower()
