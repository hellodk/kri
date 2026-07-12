"""Tests for #1003 — air-gapped installs (salt-master + node_telemetry) and the
reconfigure_minions per-node UUID-parse robustness fix.

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

import ast
import inspect
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_TASKS = REPO_ROOT / "fleet_platform" / "workers" / "ansible_tasks.py"
NODE_TELEMETRY_DIR = REPO_ROOT / "playbooks" / "roles" / "node_telemetry"
SALT_MASTER_DIR = REPO_ROOT / "playbooks" / "roles" / "salt_master"


def _ansible_tasks_source() -> str:
    return ANSIBLE_TASKS.read_text()


# ---------------------------------------------------------------------------
# Part 1 — provision_master passes salt_linux_airgap
# ---------------------------------------------------------------------------


def _provision_master_source() -> str:
    """Extract the source of provision_master via ast, for scoped assertions."""
    tree = ast.parse(_ansible_tasks_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "provision_master":
            return ast.get_source_segment(_ansible_tasks_source(), node) or ""
    raise AssertionError("provision_master function not found in ansible_tasks.py")


def test_provision_master_extravars_include_salt_linux_airgap():
    src = _provision_master_source()
    assert "_extravars" in src, "provision_master must build an _extravars dict"
    assert '"salt_linux_airgap": True' in src or "'salt_linux_airgap': True" in src, (
        "provision_master's _extravars must set salt_linux_airgap=True so a Linux "
        "master installs from the bundled onedir tarball (no apt/dnf internet fetch)"
    )


def test_salt_master_role_gates_linux_onedir_on_salt_linux_airgap():
    """Sanity-check the flag actually does something in the role (main.yml)."""
    main_yml = (SALT_MASTER_DIR / "tasks" / "main.yml").read_text()
    assert "salt_linux_airgap" in main_yml
    assert "install_linux_onedir.yml" in main_yml


# ---------------------------------------------------------------------------
# Part 2 — node_telemetry air-gap (psutil + macmon)
# ---------------------------------------------------------------------------


def _load_yaml_tasks(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list)
    return data


def _copy_arg(task: dict) -> dict:
    """Return the args dict for a copy task, whether written as `copy:` or
    the FQCN `ansible.builtin.copy:`."""
    return task.get("copy") or task.get("ansible.builtin.copy") or {}


def _shell_arg(task: dict) -> str:
    """Return the shell command string, whether written as `shell:` or the
    FQCN `ansible.builtin.shell:`."""
    return str(task.get("shell") or task.get("ansible.builtin.shell") or "")


def test_node_telemetry_install_linux_has_airgap_branch():
    tasks_path = NODE_TELEMETRY_DIR / "tasks" / "install_linux.yml"
    text = tasks_path.read_text()
    tasks = _load_yaml_tasks(tasks_path)

    # Air-gap flag gates a copy-from-playbooks/files + local (--no-index) install.
    assert "node_telemetry_airgap" in text
    assert "playbooks/files" in text or "{{ playbook_dir }}/files" in text

    copy_tasks = [t for t in tasks if "copy" in t or "ansible.builtin.copy" in t]
    assert any("psutil" in str(_copy_arg(t)).lower() for t in copy_tasks), (
        "install_linux.yml must copy a bundled psutil artifact from playbooks/files"
    )

    airgap_gated = [t for t in tasks if "node_telemetry_airgap" in str(t.get("when", ""))]
    assert airgap_gated, "at least one task must be gated on node_telemetry_airgap"

    shell_tasks = [t for t in tasks if "shell" in t or "ansible.builtin.shell" in t]
    assert any("--no-index" in _shell_arg(t) for t in shell_tasks), (
        "install_linux.yml must install psutil via pip --no-index --find-links "
        "for the air-gapped path"
    )

    # Online path (apt/dnf) must still exist, unguarded-by-default (default(false)).
    assert "apt" in text
    assert "dnf" in text
    assert "default(false)" in text


def test_node_telemetry_install_macos_has_airgap_branch():
    tasks_path = NODE_TELEMETRY_DIR / "tasks" / "install_macos.yml"
    text = tasks_path.read_text()
    tasks = _load_yaml_tasks(tasks_path)

    assert "node_telemetry_airgap" in text
    assert "{{ playbook_dir }}/files" in text

    copy_tasks = [t for t in tasks if "copy" in t or "ansible.builtin.copy" in t]
    assert any("psutil" in str(_copy_arg(t)).lower() for t in copy_tasks), (
        "install_macos.yml must copy a bundled psutil wheel dir from playbooks/files"
    )
    assert any("macmon" in str(_copy_arg(t)).lower() for t in copy_tasks), (
        "install_macos.yml must copy a bundled macmon binary from playbooks/files"
    )

    shell_tasks = [t for t in tasks if "shell" in t or "ansible.builtin.shell" in t]
    assert any("--no-index" in _shell_arg(t) for t in shell_tasks), (
        "install_macos.yml must install psutil via pip --no-index --find-links "
        "for the air-gapped path"
    )

    # Online paths (pip install --user --upgrade psutil / brew install) still present.
    assert "pip install --user --upgrade psutil" in text
    assert "brew install" in text
    assert "default(false)" in text


def test_node_telemetry_defaults_declare_airgap_flag():
    defaults_text = (NODE_TELEMETRY_DIR / "defaults" / "main.yml").read_text()
    defaults = yaml.safe_load(defaults_text)
    assert defaults.get("node_telemetry_airgap") is False


def test_node_telemetry_yaml_files_parse_cleanly():
    for name in ("install_linux.yml", "install_macos.yml", "main.yml"):
        yaml.safe_load((NODE_TELEMETRY_DIR / "tasks" / name).read_text())


# ---------------------------------------------------------------------------
# Part 3 (S4) — reconfigure_minions UUID parse inside the per-node try
# ---------------------------------------------------------------------------


def _reconfigure_minions_func():
    import fleet_platform.workers.ansible_tasks as ansible_tasks_mod

    # reconfigure_minions is decorated (celery task); unwrap to the plain
    # function for source inspection.
    func = ansible_tasks_mod.reconfigure_minions
    return getattr(func, "__wrapped__", func)


def test_reconfigure_minions_uuid_parse_is_guarded_per_node():
    """The bad-id parse must be caught locally, not raise out of the loop.

    Structural check: find the `for node_id in node_ids:` loop body and assert
    that the `_uuid.UUID(node_id)` call is the first statement inside a `try`
    block (so ValueError from a malformed id is caught and recorded as a
    per-node failure, not propagated to kill the whole batch).
    """
    func = _reconfigure_minions_func()
    source = inspect.getsource(func)
    tree = ast.parse(source)

    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)

    for_node = None
    for node in ast.walk(func_def):
        if isinstance(node, ast.For) and getattr(node.target, "id", None) == "node_id":
            for_node = node
            break
    assert for_node is not None, "expected `for node_id in node_ids:` loop"

    first_stmt = for_node.body[0]
    assert isinstance(first_stmt, ast.Try), (
        "the first statement in the per-node loop must be a try block wrapping "
        "the UUID(node_id) parse, so a malformed node_id is caught per-node"
    )

    try_body_src = ast.unparse(first_stmt)
    assert "_uuid.UUID(node_id)" in try_body_src
    assert "except" in try_body_src


def test_reconfigure_minions_bad_uuid_does_not_abort_batch(monkeypatch):
    """Behavioral: a mix of one malformed id + no valid masters/nodes must
    still return a normal ok-status report (no unhandled exception), with the
    malformed id recorded as failed.
    """
    from fleet_platform.workers import ansible_tasks as ansible_tasks_mod

    func = getattr(ansible_tasks_mod.reconfigure_minions, "__wrapped__", ansible_tasks_mod.reconfigure_minions)

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *_a, **_kw):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return None

            return _Result()

    monkeypatch.setattr(ansible_tasks_mod, "get_sync_db", lambda: _FakeSession())

    result = func(master_id="11111111-1111-1111-1111-111111111111", node_ids=["not-a-uuid"])

    assert result["status"] == "ok"
    assert "not-a-uuid" in result["failed"]
    assert result["reconfigured"] == []
