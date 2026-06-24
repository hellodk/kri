"""Tests for #494 (extravars scrub at write) and #495 (ssh_password not in broker)."""

import ast
import re
from pathlib import Path

ANSIBLE_PY = Path(__file__).parent.parent.parent / "fleet_platform/api/routes/ansible.py"
TASKS_PY = Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py"


def test_scrub_extravars_flat_secret():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"ansible_ssh_pass": "s3cr3t", "playbook_name": "test"}
    result = _scrub_extravars(ev)
    assert result["ansible_ssh_pass"] == "***"
    assert result["playbook_name"] == "test"


def test_scrub_extravars_nested_secret():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"creds": {"ansible_password": "x", "user": "foo"}}
    result = _scrub_extravars(ev)
    assert result["creds"]["ansible_password"] == "***"
    assert result["creds"]["user"] == "foo"


def test_scrub_extravars_list_of_dicts():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = [{"ansible_sudo_pass": "hunter2"}, {"safe_key": "value"}]
    result = _scrub_extravars(ev)
    assert result[0]["ansible_sudo_pass"] == "***"
    assert result[1]["safe_key"] == "value"


def test_scrub_extravars_none_returns_none():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    assert _scrub_extravars(None) is None


def test_scrub_extravars_empty_dict():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    assert _scrub_extravars({}) == {}


def test_scrub_extravars_all_sensitive_keys():
    from fleet_platform.api.routes.ansible import _SENSITIVE_EV_KEYS

    expected = {
        "ansible_ssh_pass",
        "ansible_become_password",
        "ansible_become_pass",
        "ansible_password",
        "ansible_sudo_pass",
        "vault_password",
        "password",
        "secret",
        "token",
        "api_key",
    }
    assert expected.issubset(_SENSITIVE_EV_KEYS)


def test_scrub_extravars_vault_password():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"vault_password": "topsecret", "playbook": "site.yml"}
    result = _scrub_extravars(ev)
    assert result["vault_password"] == "***"
    assert result["playbook"] == "site.yml"


def test_scrub_extravars_ansible_sudo_pass():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"ansible_sudo_pass": "sudo123", "env": "prod"}
    result = _scrub_extravars(ev)
    assert result["ansible_sudo_pass"] == "***"
    assert result["env"] == "prod"


def test_run_playbook_signature_has_no_ssh_password():
    """run_playbook task must not accept ssh_password (plaintext broker risk)."""
    src = TASKS_PY.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_playbook":
            args = [a.arg for a in node.args.args]
            assert "ssh_password" not in args, "run_playbook must not accept ssh_password"
            return
    raise AssertionError("run_playbook function not found")


def test_run_playbook_endpoint_does_not_pass_ssh_password_to_delay():
    """run_playbook_endpoint must not pass ssh_password to the run_playbook task.

    #749: the endpoint dispatches by task name via celery_app.send_task(...) rather
    than importing the worker and calling .delay(); the no-plaintext-ssh_password
    security property (#495) must still hold for the new dispatch site.
    """
    src = ANSIBLE_PY.read_text()
    match = re.search(
        r"send_task\(\s*[\"']fleet_platform\.workers\.playbook_tasks\.run_playbook[\"'].*?\)",
        src,
        re.DOTALL,
    )
    assert match, "celery_app.send_task('...run_playbook') call not found"
    assert "ssh_password" not in match.group(0), "ssh_password must not be passed to the run_playbook task"
