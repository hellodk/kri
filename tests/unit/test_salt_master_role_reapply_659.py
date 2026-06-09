# tests/unit/test_salt_master_role_reapply_659.py
"""Tests for #659: salt-master Ansible role hardening — re-apply idempotency,
dual handler notification on kri.conf change, post-restart verification.

All file paths are resolved relative to this file so the tests work in any
working directory (source-contract pattern used across this test suite).
"""

from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths — always relative to this file, never hardcoded absolute paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROLE_ROOT = _REPO_ROOT / "playbooks" / "roles" / "salt_master"
_CONFIGURE_YML = _ROLE_ROOT / "tasks" / "configure.yml"
_HANDLERS_YML = _ROLE_ROOT / "handlers" / "main.yml"
_VERIFY_YML = _ROLE_ROOT / "tasks" / "verify.yml"
_MAIN_YML = _ROLE_ROOT / "tasks" / "main.yml"
_README_MD = _ROLE_ROOT / "README.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> list:
    """Load a YAML file; return list of documents (safe_load_all)."""
    docs = list(yaml.safe_load_all(path.read_text()))
    # safe_load_all yields a single list for non-multi-document files
    if len(docs) == 1 and isinstance(docs[0], list):
        return docs[0]
    return [d for d in docs if d is not None]


def _find_task(tasks: list, name_fragment: str) -> dict | None:
    """Return the first task whose 'name' contains name_fragment (case-insensitive)."""
    for task in tasks:
        if isinstance(task, dict) and name_fragment.lower() in str(task.get("name", "")).lower():
            return task
    return None


# ---------------------------------------------------------------------------
# 1. YAML parse sanity — all touched files must be valid YAML
# ---------------------------------------------------------------------------


def test_configure_yml_parses():
    tasks = _load_yaml(_CONFIGURE_YML)
    assert tasks, "configure.yml must not be empty"


def test_handlers_yml_parses():
    handlers = _load_yaml(_HANDLERS_YML)
    assert handlers, "handlers/main.yml must not be empty"


def test_verify_yml_parses():
    tasks = _load_yaml(_VERIFY_YML)
    assert tasks, "verify.yml must not be empty"


def test_main_yml_parses():
    tasks = _load_yaml(_MAIN_YML)
    assert tasks, "tasks/main.yml must not be empty"


# ---------------------------------------------------------------------------
# 2. configure.yml: kri.conf task must notify BOTH Restart handlers
# ---------------------------------------------------------------------------


def test_kri_conf_task_notifies_restart_salt_master():
    """'Write kri salt-master configuration' must notify 'Restart salt-master'."""
    tasks = _load_yaml(_CONFIGURE_YML)
    task = _find_task(tasks, "Write kri salt-master configuration")
    assert task is not None, "'Write kri salt-master configuration' task not found in configure.yml"

    notify = task.get("notify", [])
    # notify may be a string (single) or list
    if isinstance(notify, str):
        notify = [notify]
    assert "Restart salt-master" in notify, (
        "kri.conf template task must notify 'Restart salt-master'; "
        f"current notify list: {notify}"
    )


def test_kri_conf_task_notifies_restart_salt_api():
    """'Write kri salt-master configuration' must ALSO notify 'Restart salt-api'.

    salt-api reads master.d at startup — an external_auth change in kri.conf
    requires both services to restart or the new ACL will not take effect.
    """
    tasks = _load_yaml(_CONFIGURE_YML)
    task = _find_task(tasks, "Write kri salt-master configuration")
    assert task is not None, "'Write kri salt-master configuration' task not found in configure.yml"

    notify = task.get("notify", [])
    if isinstance(notify, str):
        notify = [notify]
    assert "Restart salt-api" in notify, (
        "kri.conf template task must notify 'Restart salt-api' so that "
        "external_auth ACL changes take effect without manual intervention; "
        f"current notify list: {notify}"
    )


# ---------------------------------------------------------------------------
# 3. handlers/main.yml: required handlers exist and use become + launchctl
# ---------------------------------------------------------------------------


def test_restart_salt_master_handler_exists():
    handlers = _load_yaml(_HANDLERS_YML)
    handler = _find_task(handlers, "Restart salt-master")
    assert handler is not None, "'Restart salt-master' handler not found in handlers/main.yml"


def test_restart_salt_master_handler_uses_become():
    handlers = _load_yaml(_HANDLERS_YML)
    handler = _find_task(handlers, "Restart salt-master")
    assert handler is not None
    assert handler.get("become") is True, "'Restart salt-master' handler must set become: true"


def test_restart_salt_master_handler_uses_launchctl():
    handlers = _load_yaml(_HANDLERS_YML)
    handler = _find_task(handlers, "Restart salt-master")
    assert handler is not None
    shell_body = str(handler.get("shell", ""))
    assert "launchctl" in shell_body, (
        "'Restart salt-master' handler must use launchctl (macOS service manager)"
    )


def test_restart_salt_api_handler_exists():
    handlers = _load_yaml(_HANDLERS_YML)
    handler = _find_task(handlers, "Restart salt-api")
    assert handler is not None, "'Restart salt-api' handler not found in handlers/main.yml"


def test_restart_salt_api_handler_uses_become():
    handlers = _load_yaml(_HANDLERS_YML)
    handler = _find_task(handlers, "Restart salt-api")
    assert handler is not None
    assert handler.get("become") is True, "'Restart salt-api' handler must set become: true"


def test_restart_salt_api_handler_uses_launchctl():
    handlers = _load_yaml(_HANDLERS_YML)
    handler = _find_task(handlers, "Restart salt-api")
    assert handler is not None
    shell_body = str(handler.get("shell", ""))
    assert "launchctl" in shell_body, (
        "'Restart salt-api' handler must use launchctl (macOS service manager)"
    )


# ---------------------------------------------------------------------------
# 4. verify.yml: post-restart verification tasks exist
# ---------------------------------------------------------------------------


def test_verify_yml_waits_for_salt_api_port():
    """verify.yml must contain a wait_for task that references salt_api_port (8080)."""
    tasks = _load_yaml(_VERIFY_YML)
    found = False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        wf = task.get("wait_for", {})
        if isinstance(wf, dict):
            port_val = str(wf.get("port", ""))
            if "salt_api_port" in port_val or port_val == "8080":
                found = True
                break
        # Also check string-form wait_for (unusual but valid)
        if "salt_api_port" in str(wf) or "8080" in str(wf):
            found = True
            break
    assert found, (
        "verify.yml must contain a wait_for task for port {{ salt_api_port }} (8080)"
    )


def test_verify_yml_waits_for_salt_master_port():
    """verify.yml must contain a wait_for task for salt-master port 4505."""
    tasks = _load_yaml(_VERIFY_YML)
    found = False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        wf = task.get("wait_for", {})
        if isinstance(wf, dict) and str(wf.get("port", "")) == "4505":
            found = True
            break
    assert found, "verify.yml must contain a wait_for task for port 4505 (salt-master ZMQ)"


def test_verify_yml_has_login_readiness_probe():
    """verify.yml must contain a uri task that POSTs to /login."""
    raw_text = _VERIFY_YML.read_text()
    assert "/login" in raw_text, (
        "verify.yml must include a salt-api /login readiness probe (uri module POST /login)"
    )


def test_verify_yml_login_probe_is_skippable():
    """The /login probe must be gated on salt_api_verify so it can be disabled."""
    raw_text = _VERIFY_YML.read_text()
    assert "salt_api_verify" in raw_text, (
        "verify.yml /login probe must be conditioned on 'salt_api_verify' "
        "so operators can skip it when kri_salt_api_password is not available"
    )


# ---------------------------------------------------------------------------
# 5. main.yml: verify.yml is included as the final task file
# ---------------------------------------------------------------------------


def test_main_yml_includes_verify():
    """tasks/main.yml must import or include verify.yml."""
    raw_text = _MAIN_YML.read_text()
    assert "verify.yml" in raw_text, (
        "tasks/main.yml must import_tasks or include_tasks verify.yml "
        "so verification always runs after service startup"
    )


# ---------------------------------------------------------------------------
# 6. README.md: exists and documents become/sudo + re-apply command
# ---------------------------------------------------------------------------


def test_readme_exists():
    assert _README_MD.exists(), f"README.md not found at {_README_MD}"


def test_readme_documents_become_sudo():
    """README must mention sudo/become so operators know the prerequisite."""
    text = _README_MD.read_text()
    assert "become" in text.lower() or "sudo" in text.lower(), (
        "README.md must document the sudo/become prerequisite for running this role"
    )


def test_readme_documents_reapply_command():
    """README must include the exact command to re-apply the role against mm1."""
    text = _README_MD.read_text()
    assert "ansible-playbook" in text, (
        "README.md must include the exact ansible-playbook re-apply command for mm1"
    )
    assert "deploy_salt_master_mm1.yml" in text or "saltmaster install" in text, (
        "README.md must reference deploy_salt_master_mm1.yml or 'scripts/kri saltmaster install'"
    )
