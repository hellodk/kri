"""Tests for node_exporter deploy playbook (#292)."""
from pathlib import Path

import yaml


def test_playbook_is_valid_yaml():
    path = Path("playbooks/deploy_node_exporter.yml")
    assert path.exists(), "deploy_node_exporter.yml must exist"
    plays = yaml.safe_load(path.read_text())
    assert isinstance(plays, list)
    assert plays[0]["hosts"] == "targets"


def test_role_main_task_exists():
    path = Path("playbooks/roles/node_exporter/tasks/main.yml")
    assert path.exists()
    tasks = yaml.safe_load(path.read_text())
    assert any("import_tasks" in t or "include_tasks" in t for t in tasks)


def test_macos_task_creates_plist():
    path = Path("playbooks/roles/node_exporter/tasks/macos.yml")
    assert path.exists()
    content = path.read_text()
    assert "io.prometheus.node_exporter.plist" in content
    assert "launchctl" in content


def test_linux_task_creates_systemd_unit():
    path = Path("playbooks/roles/node_exporter/tasks/linux.yml")
    assert path.exists()
    content = path.read_text()
    assert "node_exporter.service" in content
    assert "systemd" in content
