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
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLAYBOOKS = _REPO_ROOT / "playbooks"

_GROUP_CONDITIONAL = "group: \"{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}\""


def _bootstrap_node_src() -> str:
    return (_PLAYBOOKS / "bootstrap_node.yml").read_text()


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


def test_bootstrap_gate_is_a_real_ping_wrapped_in_timeout():
    src = _bootstrap_node_src()
    assert "timeout 30 {{ salt_call_bin }} test.ping" in src, (
        "The reachability gate must run a real `test.ping` (no --local) wrapped "
        "in `timeout 30` so an unreachable master fails the gate instead of hanging."
    )
    assert "register: salt_ping" in src
    assert "until: salt_ping.rc == 0" in src


def test_heartbeat_state_apply_wrapped_in_timeout():
    src = _bootstrap_node_src()
    assert "timeout 120 {{ salt_call_bin }} state.apply base.heartbeat" in src, (
        "The heartbeat state.apply must be wrapped in `timeout 120` so it "
        "cannot block indefinitely even if the gate passed but the master "
        "later becomes unreachable."
    )


def test_process_report_state_apply_wrapped_in_timeout():
    src = _bootstrap_node_src()
    assert "timeout 120 {{ salt_call_bin }} state.apply base.process_report_schedule" in src, (
        "The process-report state.apply must be wrapped in `timeout 120`."
    )


def test_both_schedule_tasks_gated_on_salt_ping():
    src = _bootstrap_node_src()
    # There must be exactly two `when: salt_ping.rc == 0` guards — one for
    # each state.apply task (heartbeat and process_report_schedule). Prior to
    # the fix, the process-report task had NO guard at all.
    occurrences = src.count("when: salt_ping.rc == 0")
    assert occurrences >= 2, (
        "Both the heartbeat and process-report state.apply tasks must be "
        f"gated on `when: salt_ping.rc == 0` (found {occurrences} occurrence(s))."
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
