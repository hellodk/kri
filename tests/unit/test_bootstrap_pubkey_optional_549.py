"""#549: bootstrap must not fail when salt_master_pub_key is not supplied.

The master-pubkey pre-seed is an optimization (skip re-auth); in multi-master HA
it is omitted and the minion TOFU-connects + its key is accepted on the master.
The minion install itself succeeds regardless. Guard: the pre-seed task must be
conditional on `salt_master_pub_key is defined` so an absent var doesn't fail the play.

Roles-refactor Phase 3: this task moved out of the bootstrap_node.yml monolith
into playbooks/roles/salt_minion/tasks/configure.yml (a flat include_tasks file,
not a full play — hence _tasks() below loads it directly, not via play["tasks"]).
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "playbooks/roles/salt_minion/tasks/configure.yml"


def _tasks() -> list[dict]:
    tasks = yaml.safe_load(PLAYBOOK.read_text())
    return tasks if isinstance(tasks, list) else []


def _copy_arg(t: dict) -> dict:
    """Return the copy module args regardless of bare or FQCN module key."""
    val = t.get("copy", t.get("ansible.builtin.copy"))
    return val if isinstance(val, dict) else {}


def test_master_pubkey_task_is_conditional():
    """The minion_master.pub pre-seed must be guarded by salt_master_pub_key is defined."""
    pubkey_tasks = [t for t in _tasks() if "minion_master.pub" in str(_copy_arg(t).get("dest", ""))]
    assert pubkey_tasks, "expected a copy task writing minion_master.pub"
    for t in pubkey_tasks:
        when = str(t.get("when", ""))
        assert "salt_master_pub_key is defined" in when, (
            f"task {t.get('name')!r} writes minion_master.pub but is not guarded by "
            "`when: salt_master_pub_key is defined` — bootstrap will fail when the var is absent"
        )


def test_bootstrap_does_not_hard_require_pubkey_var():
    """No unconditional task may reference salt_master_pub_key (would fail the play)."""
    for t in _tasks():
        copy_arg = _copy_arg(t)
        refs_pubkey = "salt_master_pub_key" in str(copy_arg) or "salt_master_pub_key" in str(t.get("content", ""))
        if refs_pubkey:
            assert "salt_master_pub_key is defined" in str(t.get("when", "")), (
                f"task {t.get('name')!r} references salt_master_pub_key without a defined-guard"
            )
