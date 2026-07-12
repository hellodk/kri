"""Issue #991 S2 — salt-api /login probe must set no_log so the api_password is
never rendered into MasterProvisionRun.ansible_stdout on failure.

The `uri` task in verify.yml POSTs `kri_salt_api_password` to /login. Without
`no_log: true`, an Ansible task failure (wrong password / ACL misconfig — a
realistic provisioning failure) renders the full module args, including the
password, into the provision log which viewers can read via the API.

Run: pytest tests/unit/test_verify_no_log_991.py -q
"""

from pathlib import Path

import yaml

_VERIFY = Path(__file__).resolve().parents[2] / "playbooks" / "roles" / "salt_master" / "tasks" / "verify.yml"


def _tasks():
    return yaml.safe_load(_VERIFY.read_text())


def _is_login_probe(t):
    return isinstance(t, dict) and "uri" in t and "/login" in str(t.get("uri", {}).get("url", ""))


def test_login_probe_task_has_no_log():
    tasks = _tasks()
    login = [t for t in tasks if _is_login_probe(t)]
    assert login, "expected a uri task probing salt-api /login in verify.yml"
    for t in login:
        assert t.get("no_log") is True, (
            f"the salt-api /login probe task ('{t.get('name')}') must set "
            "no_log: true — it POSTs kri_salt_api_password (#991 S2)."
        )
