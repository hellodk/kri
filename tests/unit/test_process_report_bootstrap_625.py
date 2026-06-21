"""
Test that process-report schedule is applied during Mac Mini bootstrap (#625).

Tests:
1. The playbook contains the base.process_report_schedule state application
2. The task has the correct conditional (when: salt_ping.rc == 0)
3. The process_report_schedule task appears AFTER base.heartbeat
4. The playbook parses as valid YAML
"""

from pathlib import Path

import yaml


def test_process_report_schedule_exists_in_bootstrap():
    """Verify base.process_report_schedule is applied in bootstrap playbook."""
    playbook_path = Path(__file__).resolve().parents[2] / "playbooks" / "bootstrap_node.yml"
    with open(playbook_path) as f:
        content = f.read()

    assert "state.apply base.process_report_schedule" in content, (
        "process_report_schedule task not found in bootstrap playbook"
    )


def test_process_report_schedule_has_correct_conditional():
    """Verify the process_report_schedule task has when: salt_ping.rc == 0."""
    playbook_path = Path(__file__).resolve().parents[2] / "playbooks" / "bootstrap_node.yml"
    with open(playbook_path) as f:
        content = f.read()

    # Find the process_report_schedule occurrence
    idx = content.find("state.apply base.process_report_schedule")
    assert idx > 0, "process_report_schedule not found"

    # Check that the conditional appears within ~400 chars after it
    window = content[idx : idx + 400]
    assert "when: salt_ping.rc == 0" in window, (
        "process_report_schedule task missing 'when: salt_ping.rc == 0' conditional"
    )


def test_process_report_schedule_after_heartbeat():
    """Verify process_report_schedule appears AFTER base.heartbeat in the file."""
    playbook_path = Path(__file__).resolve().parents[2] / "playbooks" / "bootstrap_node.yml"
    with open(playbook_path) as f:
        content = f.read()

    heartbeat_idx = content.find("state.apply base.heartbeat")
    process_idx = content.find("state.apply base.process_report_schedule")

    assert heartbeat_idx > 0, "heartbeat task not found"
    assert process_idx > 0, "process_report_schedule task not found"
    assert process_idx > heartbeat_idx, (
        f"process_report_schedule (at {process_idx}) must appear after base.heartbeat (at {heartbeat_idx})"
    )


def test_bootstrap_playbook_valid_yaml():
    """Verify the bootstrap playbook is valid YAML."""
    playbook_path = Path(__file__).resolve().parents[2] / "playbooks" / "bootstrap_node.yml"
    with open(playbook_path) as f:
        yaml.safe_load(f)  # Will raise if invalid
