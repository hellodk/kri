"""Tests for extended playbook discovery (#300) — subdirectories and nested roles."""
import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


def test_discovers_root_level_playbooks(tmp_path):
    from fleet_platform.services.playbook_discovery import discover_all
    _write(tmp_path / "deploy.yml", """\
        - name: Deploy app
          hosts: all
          tasks: []
    """)
    results = discover_all(tmp_path)
    assert any(e.filename == "deploy.yml" for e in results)


def test_discovers_playbooks_in_subdirectory(tmp_path):
    """Playbooks in playbooks/ subdir must be discovered (#300)."""
    from fleet_platform.services.playbook_discovery import discover_all
    _write(tmp_path / "playbooks" / "setup.yml", """\
        - name: Setup nodes
          hosts: targets
          tasks: []
    """)
    results = discover_all(tmp_path)
    assert any(e.filename == "playbooks/setup.yml" for e in results), (
        f"playbooks/setup.yml not found in {[e.filename for e in results]}"
    )


def test_discovers_roles_in_playbooks_subdir(tmp_path):
    """Roles in playbooks/roles/ must be discovered (#300)."""
    from fleet_platform.services.playbook_discovery import discover_all
    _write(tmp_path / "playbooks" / "roles" / "salt_master" / "defaults" / "main.yml", """\
        # Description: Salt master role
        salt_version: "3007"
    """)
    results = discover_all(tmp_path)
    assert any("salt_master" in e.filename for e in results), (
        f"salt_master role not found in {[e.filename for e in results]}"
    )


def test_root_level_roles_still_discovered(tmp_path):
    """Existing root roles/ still works after refactor."""
    from fleet_platform.services.playbook_discovery import discover_all
    _write(tmp_path / "roles" / "my_role" / "defaults" / "main.yml", """\
        key: value
    """)
    results = discover_all(tmp_path)
    assert any("my_role" in e.filename for e in results)


def test_vars_files_not_treated_as_playbooks(tmp_path):
    """YAML files that are dicts (not lists) should not be included as playbooks."""
    from fleet_platform.services.playbook_discovery import discover_all
    _write(tmp_path / "vars.yml", "key: value\n")
    results = discover_all(tmp_path)
    assert not any(e.filename == "vars.yml" for e in results)


def test_no_duplicates_in_results(tmp_path):
    """Filenames must be unique across all discovery paths."""
    from fleet_platform.services.playbook_discovery import discover_all
    _write(tmp_path / "deploy.yml", """\
        - name: Deploy
          hosts: all
          tasks: []
    """)
    results = discover_all(tmp_path)
    filenames = [e.filename for e in results]
    assert len(filenames) == len(set(filenames)), "Duplicate filenames in discover_all results"
