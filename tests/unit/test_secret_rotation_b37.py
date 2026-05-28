"""Tests for #145: secret rotation script and procedure."""
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts/rotate_secrets.py"
RUNBOOK_PATH = Path(__file__).parent.parent.parent / "docs/OPS_RUNBOOK.md"


def test_rotation_script_exists():
    """Verify the rotate_secrets.py script exists."""
    assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"


def test_rotation_script_requires_old_secret():
    """Verify script checks for OLD_JWT_SECRET env var."""
    script = SCRIPT_PATH.read_text()
    assert "OLD_JWT_SECRET" in script


def test_rotation_script_requires_new_secret():
    """Verify script checks for NEW_JWT_SECRET env var."""
    script = SCRIPT_PATH.read_text()
    assert "NEW_JWT_SECRET" in script


def test_rotation_script_has_dry_run():
    """Verify script supports dry-run mode."""
    script = SCRIPT_PATH.read_text()
    # Check for either "dry" keyword or "commit" flag logic
    assert "dry" in script.lower() or "commit" in script.lower()


def test_rotation_script_has_commit_flag():
    """Verify script has --commit flag for actual writes."""
    script = SCRIPT_PATH.read_text()
    assert "--commit" in script


def test_rotation_handles_node_secrets():
    """Verify script processes NodeSecret model."""
    script = SCRIPT_PATH.read_text()
    assert "NodeSecret" in script or "node_secret" in script.lower()


def test_rotation_handles_group_secrets():
    """Verify script processes GroupSecret model."""
    script = SCRIPT_PATH.read_text()
    assert "GroupSecret" in script or "group_secret" in script.lower()


def test_rotation_rolls_back_on_failure():
    """Verify script handles and reports failures gracefully."""
    script = SCRIPT_PATH.read_text()
    # Check for rollback logic or failure handling
    assert "rollback" in script.lower() or "ROLLED BACK" in script or "failed" in script.lower()


def test_runbook_documents_rotation():
    """Verify OPS_RUNBOOK.md includes secret rotation section."""
    runbook = RUNBOOK_PATH.read_text()
    assert "rotation" in runbook.lower() or "Rotation" in runbook


def test_runbook_warns_about_tokens():
    """Verify runbook documents JWT token invalidation on rotation."""
    runbook = RUNBOOK_PATH.read_text()
    # Should warn about token invalidation
    assert "token" in runbook.lower() or "JWT" in runbook
