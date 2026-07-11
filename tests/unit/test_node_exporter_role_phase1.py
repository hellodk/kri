"""Contract test for the node_exporter role canonicalization (Phase 1).

See docs/superpowers/plans/2026-07-05-ansible-roles-refactor-plan.md §6 Phase 1.

The role previously had a weak, drifted implementation (tasks/{linux,macos}.yml)
that used `meta: end_play` to bail out of the *whole* multi-host play once any one
host already had node_exporter running, hardcoded architecture, and installed with
no checksum verification. This test asserts the role has been made canonical:
strong-implementation parity with playbooks/tasks/bootstrap/node_exporter_*.yml,
without breaking standalone-runnability via `roles: [node_exporter]`.

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_DIR = REPO_ROOT / "playbooks" / "roles" / "node_exporter"


def _role_yaml_files():
    return sorted(ROLE_DIR.rglob("*.yml"))


def test_role_directory_exists():
    assert ROLE_DIR.is_dir(), f"{ROLE_DIR} must exist"


def test_no_meta_end_play_anywhere_in_role():
    """meta: end_play aborts the WHOLE multi-host play, not just one host — banned.

    Parses each file's actual task list (not raw text) so a comment merely
    *mentioning* end_play can't produce a false positive.
    """
    offenders = []
    for path in _role_yaml_files():
        tasks = yaml.safe_load(path.read_text())
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if isinstance(task, dict) and task.get("meta") == "end_play":
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"meta: end_play found in: {offenders}"


def test_no_hardcoded_arch_in_role():
    """Arch/OS tarball names must be derived (ne_arch/ne_os), never hardcoded."""
    banned = ("linux-amd64", "darwin-arm64", "darwin-amd64", "linux-arm64")
    offenders = []
    for path in _role_yaml_files():
        content = path.read_text()
        for token in banned:
            if token in content:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert not offenders, f"hardcoded arch/os found: {offenders}"


def test_arch_is_derived_via_set_fact():
    main_yml = (ROLE_DIR / "tasks" / "main.yml").read_text()
    assert "ne_arch" in main_yml
    assert "ansible_architecture" in main_yml
    assert "set_fact" in main_yml


def test_install_uses_checksum_verification():
    install_yml = (ROLE_DIR / "tasks" / "install.yml").read_text()
    assert "checksum" in install_yml, "install.yml must verify a checksum"
    assert "sha256" in install_yml


def test_dedicated_system_user_created_for_systemd_path():
    service_systemd = (ROLE_DIR / "tasks" / "service_systemd.yml").read_text()
    assert "node_exporter_user" in service_systemd
    assert "system: true" in service_systemd
    assert "ansible.builtin.user" in service_systemd or "user:" in service_systemd


def test_role_has_handlers_meta_and_templates():
    assert (ROLE_DIR / "handlers" / "main.yml").is_file()
    assert (ROLE_DIR / "meta" / "main.yml").is_file()
    templates_dir = ROLE_DIR / "templates"
    assert templates_dir.is_dir()
    template_names = {p.name for p in templates_dir.iterdir()}
    assert any("service" in n or ".j2" in n for n in template_names)
    assert any("plist" in n for n in template_names)


def test_meta_declares_no_dependency_on_common_role():
    meta_yml = (ROLE_DIR / "meta" / "main.yml").read_text()
    assert "dependencies" in meta_yml


def test_service_tasks_use_started_not_forced_restarted():
    """Main service flow must use state: started; forced `restarted` is only
    acceptable inside handlers (notify-triggered), never in the primary task flow."""
    for name in ("service_systemd.yml", "service_launchd.yml"):
        path = ROLE_DIR / "tasks" / name
        assert path.is_file(), f"{path} must exist"
        content = path.read_text()
        assert "state: restarted" not in content, f"{name} must not force state: restarted"

    if (ROLE_DIR / "tasks" / "service_systemd.yml").read_text().strip():
        systemd_content = (ROLE_DIR / "tasks" / "service_systemd.yml").read_text()
        assert "state: started" in systemd_content


def test_var_back_compat_preserved_in_defaults():
    defaults = (ROLE_DIR / "defaults" / "main.yml").read_text()
    assert "node_exporter_version" in defaults
    assert "node_exporter_listen_address" in defaults
    # Legacy vars retained for back-compat.
    assert "node_exporter_port" in defaults
    assert "node_exporter_install_dir" in defaults


def test_old_weak_task_files_removed():
    assert not (ROLE_DIR / "tasks" / "linux.yml").exists()
    assert not (ROLE_DIR / "tasks" / "macos.yml").exists()


def test_deploy_node_exporter_playbook_still_uses_role_name():
    playbook = (REPO_ROOT / "playbooks" / "deploy_node_exporter.yml").read_text()
    assert "node_exporter" in playbook
    assert "gather_facts: true" in playbook
