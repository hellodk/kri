"""Contract test for issue #964 — dead tasks/bootstrap/*.yml fragments removed.

After the Phase 1–3 roles refactor, bootstrap_node.yml is a thin orchestrator
that imports roles + host_prep. These four task-include fragments were only ever
imported by the old monolithic bootstrap_node.yml; their logic now lives in the
node_telemetry / salt_minion / node_exporter roles, and nothing references them
anywhere (verified 0 references across fleet_platform/, scripts/, playbooks/).
They are also under playbooks/tasks/, which the playbook-discovery skip-list
excludes, so they are not user-invokable either.

Paths resolved via pathlib from this file (never absolute), so the test works
regardless of cwd.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP_TASKS = _REPO_ROOT / "playbooks" / "tasks" / "bootstrap"

_DEAD_FRAGMENTS = (
    "node_deps.yml",
    "minion_linux.yml",
    "node_exporter_linux.yml",
    "node_exporter_macos.yml",
)


def test_dead_bootstrap_fragments_are_deleted():
    survivors = [f for f in _DEAD_FRAGMENTS if (_BOOTSTRAP_TASKS / f).exists()]
    assert not survivors, (
        f"These dead bootstrap fragments must be deleted (logic moved into roles, "
        f"0 references anywhere): {survivors}"
    )


def test_empty_bootstrap_tasks_dir_is_removed():
    assert not _BOOTSTRAP_TASKS.exists(), (
        "playbooks/tasks/bootstrap/ holds only dead fragments and must be removed "
        "once they are deleted."
    )
