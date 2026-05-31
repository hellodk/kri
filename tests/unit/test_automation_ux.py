"""Tests for AutomationHub sync UX improvements (#297)."""


def test_automation_hub_has_syncing_state():
    """AutomationHub component must track a syncing boolean state (#297)."""
    content = open("frontend/src/pages/AutomationHub.tsx").read()
    assert "syncing" in content
    assert "setSyncing" in content


def test_automation_hub_shows_syncing_spinner():
    """Spinner shown while syncing (#297)."""
    content = open("frontend/src/pages/AutomationHub.tsx").read()
    assert "Syncing repos" in content
    assert "animate-spin" in content


def test_playbook_run_modal_close_button_explains_background():
    """Close button must explain execution continues in background."""
    content = open("frontend/src/pages/PlaybookRunModal.tsx").read()
    assert "background" in content.lower()
    assert "Executions" in content or "server" in content
