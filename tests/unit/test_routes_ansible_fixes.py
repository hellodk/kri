"""Tests for ansible.py route fixes."""

from pathlib import Path

_WORKTREE = Path(__file__).resolve().parents[2]
_SRC = (_WORKTREE / "fleet_platform/api/routes/ansible.py").read_text()


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
    # The bootstrap dispatch now lives in the shared bootstrap_svc helper. The
    # security property is the same: the SSH password is persisted to the node's
    # credential but must NEVER be forwarded to bootstrap_node.delay() (which would
    # place plaintext on the Redis broker — see #495).
    svc_src = (_WORKTREE / "fleet_platform/services/bootstrap_svc.py").read_text()
    delay_start = svc_src.find("bootstrap_node.delay(")
    assert delay_start != -1, "bootstrap_svc must dispatch via bootstrap_node.delay()"
    delay_call = svc_src[delay_start : svc_src.find(")", delay_start)]
    assert "ssh_password" not in delay_call, "bootstrap_node.delay() must not pass ssh_password"
