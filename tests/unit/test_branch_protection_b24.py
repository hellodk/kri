"""Tests for #99: coverage gate enforced in CI."""

from pathlib import Path


def test_ci_has_coverage_fail_under_gate():
    src = Path(".github/workflows/ci.yml").read_text()
    assert "--cov-fail-under=80" in src, "CI must enforce coverage gate: --cov-fail-under=80 not found in ci.yml"
