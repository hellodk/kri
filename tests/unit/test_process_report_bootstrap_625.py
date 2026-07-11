"""
Test that process-report schedule is applied during Mac Mini bootstrap (#625).

Tests:
1. The playbook contains the base.process_report_schedule state application
2. The task has the correct conditional (when: salt_ping.rc == 0)
3. The process_report_schedule task appears AFTER base.heartbeat
4. The playbook parses as valid YAML

Roles-refactor Phase 3: this logic moved out of the bootstrap_node.yml monolith
into playbooks/roles/kri_enroll/tasks/main.yml (done in Phase 2, wired up in
Phase 3), verbatim — so all assertions below read that file instead. The
conditional there is `when: salt_ping.rc | default(1) == 0` (a stricter,
async-timeout-safe form of the original `salt_ping.rc == 0`).
"""

from pathlib import Path

import yaml


def _kri_enroll_path() -> Path:
    return Path(__file__).resolve().parents[2] / "playbooks" / "roles" / "kri_enroll" / "tasks" / "main.yml"


def test_process_report_schedule_exists_in_bootstrap():
    """Verify base.process_report_schedule is applied via the kri_enroll role."""
    content = _kri_enroll_path().read_text()

    assert "state.apply base.process_report_schedule" in content, (
        "process_report_schedule task not found in kri_enroll role"
    )


def test_process_report_schedule_has_correct_conditional():
    """Verify the process_report_schedule task has the default-safe salt_ping guard."""
    content = _kri_enroll_path().read_text()

    # Find the process_report_schedule occurrence
    idx = content.find("state.apply base.process_report_schedule")
    assert idx > 0, "process_report_schedule not found"

    # Check that the conditional appears within ~400 chars after it
    window = content[idx : idx + 400]
    assert "when: salt_ping.rc | default(1) == 0" in window, (
        "process_report_schedule task missing 'when: salt_ping.rc | default(1) == 0' conditional"
    )


def test_process_report_schedule_after_heartbeat():
    """Verify process_report_schedule appears AFTER base.heartbeat in the file."""
    content = _kri_enroll_path().read_text()

    heartbeat_idx = content.find("state.apply base.heartbeat")
    process_idx = content.find("state.apply base.process_report_schedule")

    assert heartbeat_idx > 0, "heartbeat task not found"
    assert process_idx > 0, "process_report_schedule task not found"
    assert process_idx > heartbeat_idx, (
        f"process_report_schedule (at {process_idx}) must appear after base.heartbeat (at {heartbeat_idx})"
    )


def test_bootstrap_playbook_valid_yaml():
    """Verify the bootstrap playbook and the kri_enroll task file are valid YAML."""
    playbook_path = Path(__file__).resolve().parents[2] / "playbooks" / "bootstrap_node.yml"
    with open(playbook_path) as f:
        yaml.safe_load(f)  # Will raise if invalid
    with open(_kri_enroll_path()) as f:
        yaml.safe_load(f)  # Will raise if invalid
