"""Unit tests for #1006 — removal of node->master promotion feature.

Asserts the promote-node-to-master endpoint remains removed, and the
host_prep_gate.yml reachability gate remains a plain gate with no
as_master special-casing (it never regains one — #1019's master-first
bootstrap achieves reachability by ordering the Celery chain, not by
teaching the gate about as_master).

Note: #1019 deliberately reverses the *rest* of #1006's removal (the
as_master request flag + bootstrap_svc orchestration) with corrected
ordering — a provision_master→bootstrap_node Celery chain instead of the
deadlock-prone same-call ordering #1006 removed. The as_master-removed
assertions that used to live here were retired for that reason; current
behaviour is covered by tests/unit/test_master_first_bootstrap_1019.py.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return REPO_ROOT.joinpath(rel_path).read_text()


def test_promote_node_to_master_removed():
    src = _read("fleet_platform/api/routes/salt_masters.py")
    assert "promote_node_to_master" not in src
    assert "from-node" not in src


def test_as_master_removed_from_ansible_tasks():
    src = _read("fleet_platform/workers/ansible_tasks.py")
    assert "as_master" not in src


def test_host_prep_gate_fail_task_has_no_as_master_guard():
    src = _read("playbooks/tasks/host_prep_gate.yml")
    assert "as_master" not in src

    fail_task_start = src.find("Fail if no salt-master is reachable")
    assert fail_task_start != -1, "expected the reachability fail task to still exist"
    fail_task_body = src[fail_task_start:]

    when_start = fail_task_body.find("when:")
    assert when_start != -1
    when_block = fail_task_body[when_start : when_start + 400]
    assert "as_master" not in when_block
    assert (
        "master_port_results.results | selectattr('failed') | list | length "
        "== master_port_results.results | length" in when_block
    )
