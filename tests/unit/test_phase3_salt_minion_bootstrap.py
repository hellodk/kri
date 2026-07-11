"""Contract tests for the Phase 3 role extraction (roles-refactor plan).

See docs/superpowers/plans/2026-07-05-ansible-roles-refactor-plan.md §9 and the
Phase 3 dispatch brief. salt-minion install/config/service is extracted from the
bootstrap_node.yml monolith into a new `salt_minion` role, and bootstrap_node.yml
becomes a thin orchestrator that imports the Phase 1/2 roles (common,
node_telemetry, node_exporter, kri_enroll) plus the new salt_minion role and two
task files (host_prep_gate.yml, host_prep.yml).

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOKS_DIR = REPO_ROOT / "playbooks"
BOOTSTRAP_PLAYBOOK = PLAYBOOKS_DIR / "bootstrap_node.yml"
SALT_MINION_DIR = PLAYBOOKS_DIR / "roles" / "salt_minion"
HOST_PREP_GATE = PLAYBOOKS_DIR / "tasks" / "host_prep_gate.yml"
HOST_PREP = PLAYBOOKS_DIR / "tasks" / "host_prep.yml"


def _bootstrap_text() -> str:
    return BOOTSTRAP_PLAYBOOK.read_text()


def _bootstrap_plays() -> list[dict]:
    plays = yaml.safe_load(_bootstrap_text())
    # Two plays since #967 decoupled monitoring: [monitoring, salt-enrolment].
    assert isinstance(plays, list) and len(plays) == 2
    return plays


def _play_role_names(play: dict) -> list[str]:
    roles = play.get("roles", [])
    return [r if isinstance(r, str) else r.get("role", r.get("name")) for r in roles]


def _monitoring_play() -> dict:
    """The Salt-independent play — the one that runs node_exporter."""
    for play in _bootstrap_plays():
        if "node_exporter" in _play_role_names(play):
            return play
    raise AssertionError("no play runs the node_exporter role")


def _salt_play() -> dict:
    """The Salt-enrolment play — the one that runs salt_minion."""
    for play in _bootstrap_plays():
        if "salt_minion" in _play_role_names(play):
            return play
    raise AssertionError("no play runs the salt_minion role")


def _non_comment_text(path: Path) -> str:
    """File content with `#`-comment lines stripped, so explanatory comments
    that merely *mention* a banned token don't produce false-positive matches."""
    lines = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_part = line.split(" #", 1)[0] if " #" in line else line
        lines.append(code_part)
    return "\n".join(lines)


def _all_role_yaml_files() -> list[Path]:
    return sorted(SALT_MINION_DIR.rglob("*.yml"))


# ── bootstrap_node.yml: thin orchestrator ────────────────────────────────────


def test_bootstrap_playbook_exists_and_is_valid_yaml():
    assert BOOTSTRAP_PLAYBOOK.is_file()
    yaml.safe_load(_bootstrap_text())


def test_bootstrap_playbook_both_plays_host_targets():
    for play in _bootstrap_plays():
        assert play.get("hosts") == "targets", "every bootstrap play must target the 'targets' inventory group"


def test_bootstrap_playbook_keeps_play_vars():
    for play in _bootstrap_plays():
        play_vars = play.get("vars", {})
        assert play_vars.get("ansible_become") is True
        assert "ansible_become_method" in play_vars
        assert "ansible_ssh_common_args" in play_vars


def test_salt_play_roles_list_is_exact():
    role_names = _play_role_names(_salt_play())
    assert role_names == ["salt_minion", "node_telemetry", "kri_enroll"], (
        f"expected exactly [salt_minion, node_telemetry, kri_enroll], got {role_names}"
    )


def test_monitoring_play_runs_only_node_exporter():
    assert _play_role_names(_monitoring_play()) == ["node_exporter"]


def test_node_exporter_play_is_not_gated_on_salt_reachability():
    """#967: node_exporter must run in a play WITHOUT the salt reachability gate,
    so metrics land even when the master is unreachable."""
    play = _monitoring_play()
    pre_task_text = yaml.dump(play.get("pre_tasks", []))
    assert "host_prep_gate" not in pre_task_text, (
        "the node_exporter (monitoring) play must NOT import the salt reachability "
        "gate — monitoring is decoupled from Salt."
    )


def test_salt_play_imports_host_prep_tasks_in_pre_tasks():
    play = _salt_play()
    pre_task_text = yaml.dump(play.get("pre_tasks", []))
    assert "pre_tasks" in play, "the salt play must use pre_tasks for host prep"
    assert "tasks/host_prep_gate.yml" in pre_task_text
    assert "tasks/host_prep.yml" in pre_task_text


def test_bootstrap_playbook_references_none_of_the_moved_inline_salt_tasks():
    text = _bootstrap_text()
    for banned in ("installer -pkg", "Write Salt minion config", "pkgutil --pkg-info", "shasum -a 512"):
        assert banned not in text, (
            f"{banned!r} must no longer appear inline in bootstrap_node.yml — moved to salt_minion role"
        )


def test_bootstrap_playbook_does_not_reference_minion_linux_include():
    text = _bootstrap_text()
    assert "tasks/bootstrap/minion_linux.yml" not in text, (
        "bootstrap_node.yml must no longer include tasks/bootstrap/minion_linux.yml — salt_minion role replaces it"
    )


# ── salt_minion role scaffolding ──────────────────────────────────────────────


def test_salt_minion_role_directory_exists():
    assert SALT_MINION_DIR.is_dir()
    assert (SALT_MINION_DIR / "tasks" / "main.yml").is_file()


def test_salt_minion_role_has_meta_and_defaults():
    assert (SALT_MINION_DIR / "meta" / "main.yml").is_file()
    assert (SALT_MINION_DIR / "defaults" / "main.yml").is_file()


def test_salt_minion_role_has_expected_task_files():
    for name in (
        "install_macos.yml",
        "install_debian.yml",
        "install_redhat.yml",
        "configure.yml",
        "service.yml",
    ):
        assert (SALT_MINION_DIR / "tasks" / name).is_file(), f"salt_minion/tasks/{name} must exist"


def test_salt_minion_role_has_handlers():
    assert (SALT_MINION_DIR / "handlers" / "main.yml").is_file()


def test_salt_minion_role_has_minion_conf_template():
    template = SALT_MINION_DIR / "templates" / "minion.conf.j2"
    assert template.is_file()
    content = template.read_text()
    assert "OAEP-SHA1" in content
    assert "master_type: failover" in content
    assert "random_master" in content


# ── #694 preserved verbatim in the new location ──────────────────────────────


def test_salt_minion_uses_pkgutil_not_bare_binary():
    path = SALT_MINION_DIR / "tasks" / "install_macos.yml"
    content = path.read_text()
    assert "pkgutil" in content, "salt_minion/tasks/install_macos.yml must use pkgutil --pkg-info (#694)"
    # Comments legitimately explain *why not* to use the bare binary — only the
    # executable code (comments stripped) must never actually invoke it.
    assert "salt-minion --version" not in _non_comment_text(path), (
        "salt_minion/tasks/install_macos.yml must not run 'salt-minion --version' — it hangs on macOS onedir (#694)"
    )


def test_salt_minion_checksum_verify_still_present():
    content = (SALT_MINION_DIR / "tasks" / "install_macos.yml").read_text()
    assert "shasum -a 512" in content
    assert "exit 1" in content


# ── directory creation is a single file loop (spec §9 #6) ───────────────────


def test_salt_minion_configure_dir_creation_is_a_file_loop():
    tasks = yaml.safe_load((SALT_MINION_DIR / "tasks" / "configure.yml").read_text())
    file_tasks = [t for t in tasks if isinstance(t, dict) and ("file" in t or "ansible.builtin.file" in t)]
    dir_tasks = [t for t in file_tasks if "loop" in t]
    assert dir_tasks, "configure.yml must have a single looped ansible.builtin.file task for directory creation"
    loop_items = dir_tasks[0]["loop"]
    assert isinstance(loop_items, list) and len(loop_items) == 2


# ── verify-running uses service_facts, not ps aux ────────────────────────────


def test_salt_minion_service_verification_uses_service_facts():
    path = SALT_MINION_DIR / "tasks" / "service.yml"
    content = path.read_text()
    assert "service_facts" in content
    assert "ps aux" not in _non_comment_text(path), (
        "service.yml must not use 'ps aux | grep' to verify salt-minion is running"
    )


# ── host_prep_gate.yml uses wait_for, not nc ─────────────────────────────────


def test_host_prep_gate_uses_wait_for_not_nc():
    assert HOST_PREP_GATE.is_file()
    content = HOST_PREP_GATE.read_text()
    assert "wait_for" in content
    assert "nc -z" not in content


# ── host_prep.yml has no separate .ssh mkdir (§9 #12) ────────────────────────


def test_host_prep_has_no_separate_ssh_mkdir():
    assert HOST_PREP.is_file()
    content = HOST_PREP.read_text()
    assert "authorized_key" in content
    # A comment legitimately explains why no mkdir is needed — only the
    # executable code (comments stripped) must contain no actual mkdir task.
    non_comment = _non_comment_text(HOST_PREP)
    assert 'path: "~/.ssh"' not in non_comment and "path: ~/.ssh" not in non_comment, (
        "host_prep.yml must not create ~/.ssh separately — authorized_key does it"
    )


# ── no community.general anywhere in the new Phase 3 artifacts ──────────────


def test_no_community_general_in_phase3_artifacts():
    offenders = []
    for path in _all_role_yaml_files() + [HOST_PREP_GATE, HOST_PREP, BOOTSTRAP_PLAYBOOK]:
        if "community.general" in _non_comment_text(path):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"community.general referenced in: {offenders}"
