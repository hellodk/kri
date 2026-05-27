"""Tests for #99: coverage gate enforced in CI."""
from pathlib import Path


def test_ci_has_coverage_fail_under_gate():
    src = Path(".github/workflows/ci.yml").read_text()
    assert "--cov-fail-under=85" in src, (
        "CI must enforce coverage gate: --cov-fail-under=85 not found in ci.yml"
    )
