"""Property-based tests for playbook discovery using Hypothesis.

Tests that discover_all() and related helpers never crash on arbitrary
directory structures and filenames, and that their invariants hold
regardless of input.

Closes #8
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from fleet_platform.services.playbook_discovery import (
    PlaybookEntry,
    _lint_yaml,
    _parse_description,
    discover_all,
)

# ── _parse_description ────────────────────────────────────────────────────────


@given(st.text())
def test_parse_description_never_crashes(text: str) -> None:
    """_parse_description must not raise for any string input."""
    result = _parse_description(text)
    assert result is None or isinstance(result, str)


PRINTABLE_TEXT = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"), whitelist_characters=".,!?_-"),
    min_size=1,
).filter(lambda t: t.strip())


@given(PRINTABLE_TEXT)
def test_parse_description_returns_text_after_marker(text: str) -> None:
    content = f"# Description: {text}"
    result = _parse_description(content)
    assert result is not None
    assert result == text.strip()


@given(st.text().filter(lambda t: "# Description:" not in t))
def test_parse_description_returns_none_without_marker(text: str) -> None:
    assert _parse_description(text) is None


# ── _lint_yaml ────────────────────────────────────────────────────────────────


@given(st.text())
def test_lint_yaml_never_crashes(content: str) -> None:
    """_lint_yaml must return a list (possibly with errors) for any file content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    try:
        result = _lint_yaml(path)
        assert isinstance(result, list)
        assert all(isinstance(e, str) for e in result)
    finally:
        path.unlink(missing_ok=True)


@given(st.dictionaries(st.text(min_size=1, max_size=20), st.integers()))
def test_lint_yaml_valid_dict(data: dict) -> None:
    """Valid YAML dicts produce no lint errors."""
    content = yaml.dump(data)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    try:
        errors = _lint_yaml(path)
        assert errors == []
    finally:
        path.unlink(missing_ok=True)


# ── discover_all ──────────────────────────────────────────────────────────────

SAFE_FILENAME = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() and s[0].isalpha())


@given(st.lists(SAFE_FILENAME, max_size=10, unique=True))
@settings(max_examples=30, deadline=5000)
def test_discover_all_never_crashes_on_arbitrary_structure(names: list[str]) -> None:
    """discover_all must not raise regardless of what files are in the directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        for name in names:
            # Mix of valid, invalid, and empty YAML files
            (d / f"{name}.yml").write_text("- name: Test\n  hosts: all\n  tasks: []\n")
        result = discover_all(d)
        assert isinstance(result, list)
        for entry in result:
            assert isinstance(entry, PlaybookEntry)


@given(st.lists(SAFE_FILENAME, max_size=5, unique=True))
@settings(max_examples=20, deadline=5000)
def test_discover_all_with_invalid_yaml_files(names: list[str]) -> None:
    """discover_all must not crash when YAML files contain invalid content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        for name in names:
            (d / f"{name}.yml").write_text("{ this is: [not valid yaml: }\n")
        result = discover_all(d)
        assert isinstance(result, list)


@given(st.lists(SAFE_FILENAME, max_size=5, unique=True))
@settings(max_examples=20, deadline=5000)
def test_discover_all_with_empty_directory_subset(names: list[str]) -> None:
    """discover_all on empty dir always returns a list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = discover_all(Path(tmpdir))
        assert result == []


def test_discover_all_nonexistent_dir() -> None:
    """discover_all on a nonexistent directory must not crash."""
    result = discover_all(Path("/nonexistent/path/that/does/not/exist"))
    assert result == []


@given(st.lists(SAFE_FILENAME, max_size=8, unique=True))
@settings(max_examples=20, deadline=5000)
def test_discover_all_roles_never_crashes(role_names: list[str]) -> None:
    """discover_all must not crash with arbitrary role directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        roles_dir = d / "roles"
        roles_dir.mkdir()
        for name in role_names:
            role_dir = roles_dir / name
            role_dir.mkdir()
            defaults = role_dir / "defaults"
            defaults.mkdir()
            (defaults / "main.yml").write_text(f"# Description: {name} role\nsome_var: 42\n")
        result = discover_all(d)
        roles = [e for e in result if e.entry_type == "role"]
        assert len(roles) == len(role_names)
        for entry in roles:
            assert entry.entry_type == "role"
            assert isinstance(entry.default_vars, dict)


@given(st.text(max_size=200))
@settings(max_examples=30, deadline=3000)
def test_discover_all_role_with_arbitrary_defaults_content(content: str) -> None:
    """discover_all must not crash when role defaults/main.yml contains arbitrary text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        roles_dir = d / "roles"
        roles_dir.mkdir()
        role_dir = roles_dir / "testrole"
        role_dir.mkdir()
        defaults = role_dir / "defaults"
        defaults.mkdir()
        (defaults / "main.yml").write_text(content)
        result = discover_all(d)
        assert isinstance(result, list)


# ── PlaybookEntry invariants ──────────────────────────────────────────────────


def test_playbook_entry_filename_is_just_basename() -> None:
    """Discovered playbooks must use only the .yml filename, not full path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        (d / "bootstrap.yml").write_text("- name: Bootstrap\n  hosts: all\n  tasks: []\n")
        results = discover_all(d)
        assert len(results) == 1
        assert results[0].filename == "bootstrap.yml"
        assert "/" not in results[0].filename


def test_playbook_entry_type_is_always_valid() -> None:
    """Every discovered entry must have type 'playbook' or 'role'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        (d / "deploy.yml").write_text("- name: Deploy\n  hosts: all\n  tasks: []\n")
        roles_dir = d / "roles"
        roles_dir.mkdir()
        (roles_dir / "myrole").mkdir()
        results = discover_all(d)
        for entry in results:
            assert entry.entry_type in ("playbook", "role")


def test_discover_all_returns_sorted_results() -> None:
    """discover_all results should be deterministic (files sorted by name)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        for name in ["zzz.yml", "aaa.yml", "mmm.yml"]:
            (d / name).write_text("- name: Test\n  hosts: all\n  tasks: []\n")
        r1 = discover_all(d)
        r2 = discover_all(d)
        assert [e.filename for e in r1] == [e.filename for e in r2]
        assert [e.filename for e in r1] == sorted(e.filename for e in r1)
