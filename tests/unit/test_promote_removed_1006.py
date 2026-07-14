"""Unit tests for #1006 — removal of node->master promotion / as_master feature.

Asserts the promote-node-to-master endpoint and the as_master parameter/field
have been fully removed from the backend, and the host_prep_gate.yml
reachability gate no longer special-cases as_master.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return REPO_ROOT.joinpath(rel_path).read_text()


def test_promote_node_to_master_removed():
    src = _read("fleet_platform/api/routes/salt_masters.py")
    assert "promote_node_to_master" not in src
    assert "from-node" not in src


def test_as_master_removed_from_schemas():
    ansible_schema = _read("fleet_platform/schemas/ansible.py")
    assert "as_master" not in ansible_schema

    node_import_schema = _read("fleet_platform/schemas/node_import.py")
    assert "as_master" not in node_import_schema


def test_as_master_removed_from_bootstrap_svc():
    src = _read("fleet_platform/services/bootstrap_svc.py")
    assert "as_master" not in src


def test_as_master_removed_from_bootstrap_route():
    src = _read("fleet_platform/api/routes/ansible/bootstrap.py")
    assert "as_master" not in src


def test_as_master_removed_from_ansible_tasks():
    src = _read("fleet_platform/workers/ansible_tasks.py")
    assert "as_master" not in src


def test_as_master_removed_from_fleet_route():
    src = _read("fleet_platform/api/routes/fleet.py")
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
