# tests/unit/test_playbook_discovery.py
import textwrap
from pathlib import Path
import pytest
from fleet_platform.services.playbook_discovery import discover_all, PlaybookEntry


@pytest.fixture
def playbooks_dir(tmp_path):
    # Top-level playbook
    (tmp_path / "deploy_config.yml").write_text(textwrap.dedent("""\
        # Description: Push config files to all nodes
        - name: Deploy configuration
          hosts: targets
          vars:
            config_version: "1.0"
            restart_services: true
          tasks: []
    """))
    # Role with defaults
    role_dir = tmp_path / "roles" / "salt_minion"
    (role_dir / "defaults").mkdir(parents=True)
    (role_dir / "tasks").mkdir()
    (role_dir / "defaults" / "main.yml").write_text(textwrap.dedent("""\
        # Default variables for salt_minion role
        salt_master: "10.0.0.1"
        log_level: info
        grains_refresh_interval: 300
    """))
    (role_dir / "tasks" / "main.yml").write_text("---\n- name: Configure Salt\n  debug:\n    msg: ok\n")
    # Role without defaults
    role2 = tmp_path / "roles" / "basic_setup"
    (role2 / "tasks").mkdir(parents=True)
    (role2 / "tasks" / "main.yml").write_text("---\n")
    return tmp_path


def test_discover_finds_top_level_playbook(playbooks_dir):
    result = discover_all(playbooks_dir)
    filenames = {e.filename for e in result}
    assert "deploy_config.yml" in filenames


def test_discover_finds_roles(playbooks_dir):
    result = discover_all(playbooks_dir)
    names = {e.filename for e in result}
    assert "roles/salt_minion" in names
    assert "roles/basic_setup" in names


def test_playbook_extracts_vars(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    entry = result["deploy_config.yml"]
    assert entry.default_vars == {"config_version": "1.0", "restart_services": True}


def test_role_extracts_defaults(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    entry = result["roles/salt_minion"]
    assert entry.default_vars["salt_master"] == "10.0.0.1"
    assert entry.default_vars["log_level"] == "info"
    assert entry.default_vars["grains_refresh_interval"] == 300


def test_role_without_defaults_has_empty_vars(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    entry = result["roles/basic_setup"]
    assert entry.default_vars == {}


def test_discover_description_from_comment(playbooks_dir):
    result = {e.filename: e for e in discover_all(playbooks_dir)}
    assert result["deploy_config.yml"].description == "Push config files to all nodes"


def test_discover_empty_dir(tmp_path):
    assert discover_all(tmp_path) == []


def test_discover_skips_malformed_yaml(tmp_path):
    (tmp_path / "bad.yml").write_text(": : : invalid yaml {{{{")
    assert discover_all(tmp_path) == []
