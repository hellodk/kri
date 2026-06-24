"""Tests for #99: coverage gate enforced in CI (updated for #799).

The gate moved from a single ``--cov-fail-under`` to per-package floors computed
from coverage.json, so that ``fleet_platform/agent`` — previously excluded from
measurement entirely — is enforced alongside ``fleet_platform/services`` (#799).
"""

from pathlib import Path


def test_ci_enforces_per_package_coverage_floors():
    src = Path(".github/workflows/ci.yml").read_text()
    # The coverage job measures and enforces both packages at an 80% floor.
    assert "Enforce per-package coverage floors" in src, "CI must enforce a coverage gate"
    assert '"fleet_platform/services": 80' in src, "services/ must keep its 80% floor"
    assert '"fleet_platform/agent": 80' in src, "agent/ must be gated (#799), not excluded"


def test_ci_measures_agent_package():
    # Regression guard for #799: agent/ must be in the coverage measurement scope.
    src = Path(".github/workflows/ci.yml").read_text()
    assert "--cov=fleet_platform/agent" in src, "agent/ must be in --cov scope, not excluded"
