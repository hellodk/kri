"""Unit tests for #119 (dev secret warning) and #127 (Redis lifecycle management)."""

import logging
from pathlib import Path

import pytest


def test_config_warns_in_dev_for_insecure_secret(caplog):
    """Settings must log a warning when jwt_secret is insecure in non-production."""
    from fleet_platform.core.config import Settings

    with caplog.at_level(logging.WARNING, logger="fleet_platform.core.config"):
        Settings(jwt_secret="short", environment="development")

    assert any("insecure" in r.message.lower() or "JWT_SECRET" in r.message for r in caplog.records), (
        "Expected a warning about insecure JWT_SECRET in dev mode"
    )


def test_config_still_raises_in_production():
    """Settings must raise ValueError when environment=production and jwt_secret is insecure."""
    from fleet_platform.core.config import Settings

    with pytest.raises(ValueError, match="JWT_SECRET must be at least 32"):
        Settings(jwt_secret="short", environment="production")


def test_config_no_warning_for_valid_secret(caplog):
    """Settings must not warn when jwt_secret is long and not in the insecure set."""
    from fleet_platform.core.config import Settings

    with caplog.at_level(logging.WARNING, logger="fleet_platform.core.config"):
        Settings(jwt_secret="a" * 32, environment="development")

    assert not any("JWT_SECRET" in r.message for r in caplog.records), (
        "Settings must not warn when jwt_secret meets length requirement"
    )


def test_deps_has_init_and_close_redis():
    """deps.py must expose init_redis and close_redis with health_check_interval."""
    src = Path("fleet_platform/api/deps.py").read_text()
    assert "init_redis" in src, "deps.py must have init_redis()"
    assert "close_redis" in src, "deps.py must have close_redis()"
    assert "health_check_interval" in src, "init_redis must set health_check_interval"


def test_main_lifespan_calls_both_redis_lifecycle():
    """main.py lifespan must call BOTH init_redis (startup) and close_redis (shutdown)."""
    src = Path("fleet_platform/api/main.py").read_text()
    assert "init_redis" in src, "main.py lifespan must call init_redis() on startup"
    assert "close_redis" in src, "main.py lifespan must call close_redis() on shutdown"
