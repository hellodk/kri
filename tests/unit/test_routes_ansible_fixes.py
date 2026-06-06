"""Tests for ansible.py route fixes."""

from pathlib import Path

_SRC = Path("fleet_platform/api/routes/ansible.py").read_text()


def test_extravars_scrub_helper_exists():
    assert "_scrub_extravars" in _SRC


def test_extravars_scrub_removes_sensitive():
    # Import and call the helper directly
    from fleet_platform.api.routes.ansible import _scrub_extravars

    result = _scrub_extravars({"ansible_ssh_pass": "secret", "playbook": "site.yml"})
    assert result["ansible_ssh_pass"] == "***"
    assert result["playbook"] == "site.yml"


def test_cancel_uses_email_actor():
    start = _SRC.find("async def cancel_playbook_job")
    segment = _SRC[start : start + 2000]
    assert 'claims.get("email")' in segment, "cancel must use email as actor"


def test_cancel_audit_before_commit():
    start = _SRC.find("async def cancel_playbook_job")
    segment = _SRC[start : start + 2000]
    audit_pos = segment.find("await audit(")
    commit_pos = segment.find("await db.commit()")
    assert audit_pos < commit_pos, "audit() must be called before db.commit() in cancel"


def test_bootstrap_delay_no_ssh_password():
    # Only check the bootstrap() function body, not the whole file
    # (run_playbook_endpoint legitimately passes ssh_password)
    start = _SRC.find("async def bootstrap(")
    end = _SRC.find("\n@router.", start + 1)
    bootstrap_fn = _SRC[start:end]
    assert "ssh_password=payload.ssh_password" not in bootstrap_fn, "bootstrap_node.delay() must not pass ssh_password"
