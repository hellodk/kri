"""Tests for node_exporter deploy playbook (#292)."""

from pathlib import Path

import yaml


def test_role_main_task_exists():
    path = Path("playbooks/roles/node_exporter/tasks/main.yml")
    assert path.exists()
    tasks = yaml.safe_load(path.read_text())
    include_keys = ("import_tasks", "include_tasks", "ansible.builtin.import_tasks", "ansible.builtin.include_tasks")
    assert any(any(key in t for key in include_keys) for t in tasks)


def test_macos_task_creates_plist():
    # Phase 1 refactor: macos.yml -> service_launchd.yml (canonical role, #see
    # docs/superpowers/plans/2026-07-05-ansible-roles-refactor-plan.md §6).
    path = Path("playbooks/roles/node_exporter/tasks/service_launchd.yml")
    assert path.exists()
    content = path.read_text()
    assert "io.prometheus.node_exporter.plist" in content
    assert "launchctl" in content


def test_linux_task_creates_systemd_unit():
    # Phase 1 refactor: linux.yml -> service_systemd.yml (canonical role).
    path = Path("playbooks/roles/node_exporter/tasks/service_systemd.yml")
    assert path.exists()
    content = path.read_text()
    assert "node_exporter.service" in content
    assert "systemd" in content
