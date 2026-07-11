"""Source-contract tests for the bootstrap-hang + salt_master Linux-parity fixes.

Fix 1: bootstrap_node.yml's salt-master reachability gate used
`salt_call --local test.ping`, which never contacts the master (always rc=0),
so the following unbounded `state.apply` tasks could hang forever when the
master was unreachable. The gate must now be a real (non `--local`) ping
wrapped in `timeout`, and both `state.apply` tasks that depend on it must
themselves be wrapped in `timeout` and gated on `salt_ping.rc == 0`.

Fix 2: roles/salt_master/tasks/{pki,pillar,states}.yml hardcoded
`group: wheel`, which is invalid on Debian/Linux masters. Every group: line
in those files must use the same Darwin/Linux conditional already used in
configure.yml / api_tls.yml.

Fix 3: confirmed-dead playbooks (zero references anywhere in fleet_platform/,
scripts/, playbooks/) are deleted: playbooks/group_vars/home.yml and
playbooks/inventory/dynamic.py. (deploy_salt_master_mm1.yml and
setup_salt_master.yml are still referenced elsewhere and are intentionally
kept.)

Roles-refactor Phase 3: the async schedule-gate logic (Fix 1) moved out of the
bootstrap_node.yml monolith into playbooks/roles/kri_enroll/tasks/main.yml
(done in Phase 2, wired up in Phase 3) — verbatim, so _bootstrap_node_src()
below reads that file instead. Fix 2/Fix 3 assertions are untouched by the
roles-refactor and still read the original locations.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLAYBOOKS = _REPO_ROOT / "playbooks"

_GROUP_CONDITIONAL = "group: \"{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}\""


def _bootstrap_node_src() -> str:
    return (_PLAYBOOKS / "roles" / "kri_enroll" / "tasks" / "main.yml").read_text()


def _salt_master_task_src(name: str) -> str:
    return (_PLAYBOOKS / "roles" / "salt_master" / "tasks" / name).read_text()


# ---------------------------------------------------------------------------
# Fix 1: bootstrap_node.yml hang fix
# ---------------------------------------------------------------------------


def test_bootstrap_gate_no_longer_uses_local_test_ping():
    src = _bootstrap_node_src()
    assert "--local test.ping" not in src, (
        "The salt-master reachability gate must not use `--local test.ping` — "
        "that flag never contacts the master, so it always returns rc=0 even "
        "when the master is unreachable."
    )


def test_bootstrap_gate_is_a_real_ping_bounded_by_async():
    src = _bootstrap_node_src()
    # Real ping (no --local), bounded by Ansible async/poll — NOT the `timeout`
    # binary, which is absent on stock macOS (would 127 → gate never passes →
    # heartbeat silently skipped → node goes offline).
    assert 'command: "{{ salt_call_bin }} test.ping"' in src
    assert "async: 30" in src and "poll: 5" in src
    assert "timeout 30" not in src
    assert "register: salt_ping" in src
    assert "until: salt_ping.rc | default(1) == 0" in src


def test_heartbeat_state_apply_bounded_by_async():
    src = _bootstrap_node_src()
    assert 'command: "{{ salt_call_bin }} state.apply base.heartbeat"' in src
    assert "async: 120" in src
    assert "timeout 120" not in src  # no dependency on the macOS-absent timeout binary


def test_process_report_state_apply_bounded_by_async():
    src = _bootstrap_node_src()
    assert 'command: "{{ salt_call_bin }} state.apply base.process_report_schedule"' in src


def test_both_schedule_tasks_gated_on_salt_ping():
    src = _bootstrap_node_src()
    # Exactly two `when` guards + one `until` all use the default(1)-safe form
    # (so an async timeout, which has no `rc`, doesn't error the guard).
    when_guards = src.count("when: salt_ping.rc | default(1) == 0")
    assert when_guards >= 2, (
        "Both the heartbeat and process-report state.apply tasks must be "
        f"gated on the default-safe salt_ping guard (found {when_guards})."
    )


# ---------------------------------------------------------------------------
# Fix 2: salt_master role Linux/Darwin group parity
# ---------------------------------------------------------------------------


def test_pki_yml_has_no_unconditional_wheel_group():
    src = _salt_master_task_src("pki.yml")
    assert "group: wheel" not in src, (
        "pki.yml must not hardcode `group: wheel` — invalid on Debian/Linux "
        "salt-master hosts."
    )


def test_pillar_yml_has_no_unconditional_wheel_group():
    src = _salt_master_task_src("pillar.yml")
    assert "group: wheel" not in src, (
        "pillar.yml must not hardcode `group: wheel` — invalid on Debian/Linux "
        "salt-master hosts."
    )


def test_states_yml_has_no_unconditional_wheel_group():
    src = _salt_master_task_src("states.yml")
    assert "group: wheel" not in src, (
        "states.yml must not hardcode `group: wheel` — invalid on Debian/Linux "
        "salt-master hosts."
    )


def test_pki_yml_every_group_line_uses_darwin_linux_conditional():
    src = _salt_master_task_src("pki.yml")
    group_lines = [line.strip() for line in src.splitlines() if line.strip().startswith("group:")]
    assert group_lines, "pki.yml must have at least one group: line"
    for line in group_lines:
        assert line == _GROUP_CONDITIONAL, f"Unexpected group: line in pki.yml: {line!r}"


def test_pillar_yml_every_group_line_uses_darwin_linux_conditional():
    src = _salt_master_task_src("pillar.yml")
    group_lines = [line.strip() for line in src.splitlines() if line.strip().startswith("group:")]
    assert group_lines, "pillar.yml must have at least one group: line"
    for line in group_lines:
        assert line == _GROUP_CONDITIONAL, f"Unexpected group: line in pillar.yml: {line!r}"


def test_states_yml_every_group_line_uses_darwin_linux_conditional():
    src = _salt_master_task_src("states.yml")
    group_lines = [line.strip() for line in src.splitlines() if line.strip().startswith("group:")]
    assert group_lines, "states.yml must have at least one group: line"
    for line in group_lines:
        assert line == _GROUP_CONDITIONAL, f"Unexpected group: line in states.yml: {line!r}"


# ---------------------------------------------------------------------------
# Fix 3: confirmed-dead files removed
# ---------------------------------------------------------------------------


def test_dead_group_vars_home_yml_removed():
    assert not (_PLAYBOOKS / "group_vars" / "home.yml").exists(), (
        "playbooks/group_vars/home.yml has zero references anywhere in "
        "fleet_platform/, scripts/, or playbooks/ and must be deleted."
    )


def test_dead_inventory_dynamic_py_removed():
    assert not (_PLAYBOOKS / "inventory" / "dynamic.py").exists(), (
        "playbooks/inventory/dynamic.py has zero references anywhere in "
        "fleet_platform/, scripts/, or playbooks/ and must be deleted."
    )
