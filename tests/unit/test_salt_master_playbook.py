"""Tests for salt-master deploy playbook and node_exporter salt state."""

from pathlib import Path

import yaml


def test_deploy_salt_master_playbook_exists():
    path = Path("playbooks/deploy_salt_master_mm1.yml")
    assert path.exists(), "deploy_salt_master_mm1.yml must exist"
    plays = yaml.safe_load(path.read_text())
    assert isinstance(plays, list)
    assert plays[0]["hosts"] == "all"  # updated: kri uses all to target selected nodes


def test_deploy_salt_master_applies_role():
    path = Path("playbooks/deploy_salt_master_mm1.yml")
    content = path.read_text()
    assert "salt_master" in content


def test_node_exporter_sls_exists():
    path = Path("salt/states/monitoring/node_exporter.sls")
    assert path.exists()


def test_node_exporter_sls_is_idempotent():
    path = Path("salt/states/monitoring/node_exporter.sls")
    content = path.read_text()
    assert "unless" in content, "state must be idempotent (use unless:)"


def test_node_exporter_sls_creates_plist():
    path = Path("salt/states/monitoring/node_exporter.sls")
    content = path.read_text()
    assert "io.prometheus.node_exporter.plist" in content
    assert "launchctl" in content
    assert ":9100" in content
