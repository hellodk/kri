"""Contract tests for the Phase 2 role extraction (roles-refactor plan).

See docs/superpowers/plans/2026-07-05-ansible-roles-refactor-plan.md §9 and the
Phase 2 dispatch brief. Three new roles are extracted from the bootstrap_node.yml
monolith + tasks/bootstrap/node_deps.yml:

    common          — OS/arch fact normalization (cpu_arch, ne_arch, ne_os,
                       salt_call_bin, salt_group, brew_prefix, brew_user)
    node_telemetry  — psutil / macmon / tart installation
    kri_enroll      — salt schedule application + grains push to kri ingest API

§9 locks: ansible.builtin / ansible.posix only (no community.general), FQCN
throughout, gathered facts preferred over raw/shell where a module or fact
exists.

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLES_DIR = REPO_ROOT / "playbooks" / "roles"
COMMON_DIR = ROLES_DIR / "common"
NODE_TELEMETRY_DIR = ROLES_DIR / "node_telemetry"
KRI_ENROLL_DIR = ROLES_DIR / "kri_enroll"

ALL_PHASE2_ROLE_DIRS = (COMMON_DIR, NODE_TELEMETRY_DIR, KRI_ENROLL_DIR)


def _yaml_files(role_dir: Path):
    return sorted((role_dir / "tasks").rglob("*.yml")) if (role_dir / "tasks").is_dir() else []


def _load_tasks(path: Path):
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, list) else []


def _non_comment_text(path: Path) -> str:
    """File content with `#`-comment lines stripped, so explanatory comments
    that merely *mention* a banned token (e.g. "NOT community.general") don't
    produce false-positive matches."""
    lines = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Strip trailing inline comments conservatively (no '#' occurs inside
        # any value used in these roles, e.g. no URLs/regexes containing '#').
        code_part = line.split(" #", 1)[0] if " #" in line else line
        lines.append(code_part)
    return "\n".join(lines)


# ── Role scaffolding exists ──────────────────────────────────────────────────


def test_all_three_role_directories_exist():
    for role_dir in ALL_PHASE2_ROLE_DIRS:
        assert role_dir.is_dir(), f"{role_dir} must exist"
        assert (role_dir / "tasks" / "main.yml").is_file(), f"{role_dir}/tasks/main.yml must exist"


def test_all_three_roles_have_meta_and_defaults():
    for role_dir in ALL_PHASE2_ROLE_DIRS:
        assert (role_dir / "meta" / "main.yml").is_file(), f"{role_dir}/meta/main.yml must exist"
        assert (role_dir / "defaults" / "main.yml").is_file(), f"{role_dir}/defaults/main.yml must exist"


# ── No community.general anywhere in the three new roles (§9 collection policy) ──


def test_no_community_general_in_any_phase2_role():
    offenders = []
    for role_dir in ALL_PHASE2_ROLE_DIRS:
        for path in role_dir.rglob("*.yml"):
            if "community.general" in _non_comment_text(path):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"community.general referenced in: {offenders}"


# ── common role: arch derived from gathered facts, not raw/uname ────────────


def test_common_role_derives_arch_from_gathered_facts():
    main_yml = (COMMON_DIR / "tasks" / "main.yml").read_text()
    assert "ansible_architecture" in main_yml
    assert "cpu_arch" in main_yml
    assert "ne_arch" in main_yml
    assert "set_fact" in main_yml


def test_common_role_has_no_raw_uname():
    for path in _yaml_files(COMMON_DIR):
        content = _non_comment_text(path)
        assert "raw: uname" not in content, f"{path}: raw uname -m must not be used (§9 #1)"
        assert "uname -m" not in content, f"{path}: uname -m must not be used (§9 #1)"


def test_common_role_sets_brew_user_facts():
    main_yml = (COMMON_DIR / "tasks" / "main.yml").read_text()
    assert "brew_user" in main_yml
    assert "brew_prefix" in main_yml
    assert "salt_call_bin" in main_yml
    assert "salt_group" in main_yml
    assert "ne_os" in main_yml


# ── node_telemetry role: loop + creates + changed_when idempotency (§9 #9) ──


def test_node_telemetry_macmon_tart_use_guarded_loop_shell():
    install_macos_path = NODE_TELEMETRY_DIR / "tasks" / "install_macos.yml"
    install_macos = _non_comment_text(install_macos_path)
    tasks = _load_tasks(install_macos_path)

    brew_tasks = [
        t
        for t in tasks
        if isinstance(t, dict) and "brew install" in str(t.get("shell", t.get("ansible.builtin.shell", "")))
    ]
    assert brew_tasks, "install_macos.yml must have a shell task running `brew install`"

    brew_task = brew_tasks[0]
    assert "loop" in brew_task, "macmon/tart install must be a single looped task"
    assert "creates" in str(brew_task.get("args", {})), "brew install task must use `creates` for idempotency"
    assert brew_task.get("changed_when") is not None

    # community.general.homebrew must not be used anywhere in the role.
    assert "community.general" not in install_macos


def test_node_telemetry_installs_psutil_on_linux():
    install_linux = (NODE_TELEMETRY_DIR / "tasks" / "install_linux.yml").read_text()
    assert "psutil" in install_linux
    assert "ansible.builtin.apt" in install_linux
    assert "ansible.builtin.dnf" in install_linux


def test_node_telemetry_defaults_declares_package_lists():
    defaults = (NODE_TELEMETRY_DIR / "defaults" / "main.yml").read_text()
    assert "node_telemetry_brew_packages" in defaults
    assert "macmon" in defaults
    # tart removed 2026-07-11 (not needed on the fleet).
    assert "tart" not in defaults, "tart should no longer be installed"


# ── kri_enroll role: exactly one grains uri task, async gate preserved ───────


def test_kri_enroll_has_exactly_one_grains_uri_task():
    tasks = _load_tasks(KRI_ENROLL_DIR / "tasks" / "main.yml")
    uri_tasks = [
        t
        for t in tasks
        if isinstance(t, dict) and ("uri" in t or "ansible.builtin.uri" in t)
    ]
    assert len(uri_tasks) == 1, f"expected exactly one uri task (§9 #7), found {len(uri_tasks)}"

    grains_body = uri_tasks[0].get("ansible.builtin.uri", uri_tasks[0].get("uri", {}))
    assert "/grains" in grains_body.get("url", "")
    # OS-conditional body, not two separate macOS/Linux uri blocks.
    assert "ansible_os_family" in yaml.dump(grains_body)


def test_kri_enroll_uses_gathered_facts_for_os_cpu_ram_model():
    main_yml = (KRI_ENROLL_DIR / "tasks" / "main.yml").read_text()
    for gathered_fact in (
        "ansible_distribution_version",
        "ansible_processor_vcpus",
        "ansible_memtotal_mb",
        "ansible_product_name",
    ):
        assert gathered_fact in main_yml, f"{gathered_fact} must be used (§9 #4)"
    # Only the macOS serial keeps a scoped shell call.
    assert "system_profiler SPHardwareDataType" in main_yml


def test_kri_enroll_preserves_async_gate_exactly():
    main_yml = (KRI_ENROLL_DIR / "tasks" / "main.yml").read_text()
    assert "async: 30" in main_yml, "test.ping async gate must be preserved (fixes a hang)"
    assert "async: 120" in main_yml, "state.apply async gate must be preserved (fixes a hang)"
    assert "salt_ping.rc | default(1)" in main_yml
    assert "test.ping" in main_yml
    assert "state.apply base.heartbeat" in main_yml
    assert "state.apply base.process_report_schedule" in main_yml


def test_kri_enroll_grains_task_guarded_on_ingest_vars():
    main_yml = (KRI_ENROLL_DIR / "tasks" / "main.yml").read_text()
    assert "when: ingest_url is defined and node_token is defined" in main_yml


# ── FQCN throughout (no bare module names in Phase 2 roles) ──────────────────


def test_phase2_roles_use_fqcn_for_common_modules():
    bare_module_prefixes = (
        "- set_fact:",
        "- command:",
        "- shell:",
        "- apt:",
        "- dnf:",
        "- uri:",
        "- include_tasks:",
    )
    offenders = []
    for role_dir in ALL_PHASE2_ROLE_DIRS:
        for path in _yaml_files(role_dir):
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith(bare_module_prefixes):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {stripped}")
    assert not offenders, f"bare module names found (need FQCN): {offenders}"
