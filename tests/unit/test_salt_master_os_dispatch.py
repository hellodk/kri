"""Tests for OS-aware salt_master role dispatch (#359).

These tasks are Ansible YAML; their *runtime* behaviour (set_fact resolution,
``include_tasks`` dispatch, ``when`` evaluation) can only be exercised by an
Ansible execution engine against real target hosts, which is out of scope for a
unit test. So rather than executing the role, we parse the task files with PyYAML
and assert on the *structure of the parsed task graph*. This is strictly stronger
than the previous raw-substring checks: it fails if a file is not valid YAML, if
the dispatch task is wired to the wrong module/argument, or if the OS-selection
fact is restructured — none of which a plain ``"x" in text`` assertion catches.
"""

from pathlib import Path

import yaml

ROLE = Path(__file__).resolve().parents[2] / "playbooks" / "roles" / "salt_master" / "tasks"

# Ansible task directives that are NOT modules; whatever key remains is the module.
_DIRECTIVES = {
    "name",
    "when",
    "become",
    "become_user",
    "register",
    "changed_when",
    "failed_when",
    "ignore_errors",
    "args",
    "delegate_to",
    "local_action",
    "timeout",
    "tags",
    "loop",
    "with_items",
    "notify",
    "vars",
    "block",
    "rescue",
    "always",
    "no_log",
    "environment",
    "run_once",
}


def _load_tasks(filename: str) -> list[dict]:
    data = yaml.safe_load((ROLE / filename).read_text())
    assert isinstance(data, list), f"{filename} must parse to a list of tasks"
    return data


def _module_of(task: dict) -> str | None:
    for key in task:
        if key not in _DIRECTIVES:
            return key
    return None


def test_os_install_files_exist():
    for f in ["install_macos.yml", "install_debian.yml", "install_redhat.yml"]:
        assert (ROLE / f).exists(), f"{f} must exist"


def test_service_files_exist():
    assert (ROLE / "service_macos.yml").exists()
    assert (ROLE / "service_systemd.yml").exists()


def test_main_sets_salt_os_fact_from_os_family():
    """main.yml must derive a ``_salt_os`` fact from ansible_system/ansible_os_family."""
    tasks = _load_tasks("main.yml")
    set_fact_tasks = [t for t in tasks if "set_fact" in t and isinstance(t["set_fact"], dict)]
    os_fact = next((t for t in set_fact_tasks if "_salt_os" in t["set_fact"]), None)
    assert os_fact is not None, "main.yml must set_fact a `_salt_os` variable"
    expr = str(os_fact["set_fact"]["_salt_os"])
    assert "ansible_system" in expr
    assert "ansible_os_family" in expr
    assert "unsupported" in expr, "the OS-selection fact must have an 'unsupported' fallback"


def test_main_dispatches_install_by_os_via_include_tasks():
    """A task must dynamically include ``install_{{ _salt_os }}.yml``."""
    tasks = _load_tasks("main.yml")
    includes = [str(t["include_tasks"]) for t in tasks if "include_tasks" in t]
    assert any(inc == "install_{{ _salt_os }}.yml" for inc in includes), (
        f"main.yml must dispatch install by OS via include_tasks; found includes: {includes}"
    )


def test_main_fails_clearly_on_unsupported_os():
    """An explicit fail task must guard the unsupported-OS case."""
    tasks = _load_tasks("main.yml")
    fail_tasks = [t for t in tasks if "fail" in t]
    assert fail_tasks, "main.yml must contain a `fail` task for unsupported OSes"
    assert any("_salt_os == 'unsupported'" in str(t.get("when", "")) for t in fail_tasks), (
        "the fail task must be gated on `_salt_os == 'unsupported'`"
    )


def test_macos_install_uses_full_path_installer():
    """The macOS install must invoke the absolute-path installer binary."""
    tasks = _load_tasks("install_macos.yml")
    shell_cmds = [str(t.get("shell", "")) for t in tasks if "shell" in t]
    assert any("/usr/sbin/installer" in cmd for cmd in shell_cmds), (
        "install_macos.yml must run /usr/sbin/installer in a shell task"
    )


def test_debian_install_uses_apt_for_salt_master():
    """The Debian install must use the apt module to install salt-master."""
    tasks = _load_tasks("install_debian.yml")
    apt_tasks = [t for t in tasks if _module_of(t) == "apt"]
    assert apt_tasks, "install_debian.yml must use the apt module"
    assert any("salt-master" in str(t["apt"]) for t in apt_tasks), (
        "an apt task in install_debian.yml must install salt-master"
    )


def test_redhat_install_uses_dnf_or_yum_for_salt_master():
    """The RedHat install must use the dnf (or yum) module to install salt-master."""
    tasks = _load_tasks("install_redhat.yml")
    pkg_tasks = [t for t in tasks if _module_of(t) in {"dnf", "yum"}]
    assert pkg_tasks, "install_redhat.yml must use the dnf or yum module"
    assert any("salt-master" in str(t[_module_of(t)]) for t in pkg_tasks), (
        "a dnf/yum task in install_redhat.yml must install salt-master"
    )
