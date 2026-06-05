"""Tests for #6: mutation testing infrastructure."""

from pathlib import Path


def test_mutmut_in_dev_dependencies():
    pyproject = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
    assert "mutmut" in pyproject


def test_run_script_exists():
    script = Path(__file__).parent.parent.parent / "scripts/run_mutation_tests.sh"
    assert script.exists()
    content = script.read_text()
    assert "mutmut" in content


def test_run_script_is_executable():
    import stat

    script = Path(__file__).parent.parent.parent / "scripts/run_mutation_tests.sh"
    assert script.exists()
    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR  # owner execute bit set


def test_mutation_docs_exist():
    docs = Path(__file__).parent.parent.parent / "docs/MUTATION_TESTING.md"
    assert docs.exists()
    content = docs.read_text()
    assert "mutmut" in content


def test_mutation_docs_has_quick_start():
    docs = (Path(__file__).parent.parent.parent / "docs/MUTATION_TESTING.md").read_text()
    assert "Quick Start" in docs or "quick start" in docs.lower()


def test_mutation_docs_has_target_score():
    docs = (Path(__file__).parent.parent.parent / "docs/MUTATION_TESTING.md").read_text()
    assert "80%" in docs or "killed" in docs.lower()


def test_pyproject_has_mutmut_config():
    pyproject = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
    assert "mutmut" in pyproject
    assert "paths_to_mutate" in pyproject or "services" in pyproject
