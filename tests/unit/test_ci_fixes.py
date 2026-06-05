"""Unit tests for CI pipeline fixes (#121, #125)."""

from pathlib import Path

CI = Path(".github/workflows/ci.yml").read_text()


def test_unit_tests_job_has_redis_service():
    """unit-tests job must run a Redis service container."""
    # Find the unit-tests job section and check for redis service
    assert "redis:" in CI, "CI unit-tests job must declare a Redis service"
    assert "redis:7" in CI or "redis:7.4" in CI, "Redis service must use redis:7.x image"


def test_coverage_job_has_redis_service():
    """coverage job must also have Redis service."""
    coverage_section = CI[CI.find("coverage:") :]
    assert "redis:" in coverage_section, "CI coverage job must also have a Redis service"


def test_bandit_job_exists():
    """CI must run bandit security scan."""
    assert "bandit" in CI, "CI must have a bandit security scan job"
    assert "bandit -r fleet_platform" in CI, "bandit must scan fleet_platform/"


def test_vulture_job_exists():
    """CI must run vulture dead code detection."""
    assert "vulture" in CI, "CI must have a vulture dead code detection job"
    assert "vulture fleet_platform" in CI, "vulture must scan fleet_platform/"
