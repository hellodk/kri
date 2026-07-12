"""Issue #993 — self-master bootstrap must not deadlock on the reachability gate.

A node bootstrapped as its own salt-master (`as_master=true`, salt_masters=[self])
used to deadlock: `host_prep_gate.yml` hard-fails when the master is unreachable
on 4505/4506, but the master is only provisioned AFTER a successful bootstrap
(the `as_master` block) — so the gate could never pass and the master was never
installed.

Fix: pass `as_master` into the bootstrap playbook extravars and skip the gate's
hard-fail for self-master nodes. The existing tested provision_master path brings
the master up post-bootstrap; the already-configured minion connects on its next
schedule cycle (kri_enroll is already non-fatal via failed_when: false).

Run: pytest tests/unit/test_self_master_gate_993.py -q
"""

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_ANSIBLE_TASKS = (_ROOT / "fleet_platform" / "workers" / "ansible_tasks.py").read_text()
_GATE = _ROOT / "playbooks" / "tasks" / "host_prep_gate.yml"


def test_as_master_passed_into_bootstrap_extravars():
    assert '"as_master": as_master' in _ANSIBLE_TASKS, (
        "bootstrap_node must inject as_master into the playbook extravars so "
        "host_prep_gate.yml can see it (#993)."
    )


def test_gate_fail_task_skipped_for_self_master():
    tasks = yaml.safe_load(_GATE.read_text())
    fail_tasks = [t for t in tasks if isinstance(t, dict) and "ansible.builtin.fail" in t]
    assert fail_tasks, "expected the reachability fail task in host_prep_gate.yml"
    for t in fail_tasks:
        when = t.get("when")
        assert isinstance(when, list), "the fail task's when must be a list of conditions (#993)"
        joined = " ".join(str(c) for c in when)
        assert "as_master" in joined and "not (" in joined, (
            "the reachability fail task must be guarded so self-master nodes "
            "(as_master=true) skip it (#993)."
        )


def test_gate_still_fails_for_normal_nodes():
    """Regression guard: the fail condition (all probes failed) is still present —
    a normal node with an unreachable master must still fail fast."""
    tasks = yaml.safe_load(_GATE.read_text())
    fail_tasks = [t for t in tasks if isinstance(t, dict) and "ansible.builtin.fail" in t]
    joined = " ".join(str(c) for t in fail_tasks for c in t.get("when", []))
    assert "master_port_results.results" in joined and "failed" in joined, (
        "the fail task must retain the 'all probes failed' condition for normal nodes."
    )
