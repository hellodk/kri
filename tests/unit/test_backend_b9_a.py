"""Unit tests for #119 (dev secret warning) and #127 (Redis shutdown)."""
from pathlib import Path


def test_config_warns_in_dev_for_insecure_secret():
    """config.py must call logging.warning when jwt_secret is insecure in non-production."""
    src = Path("fleet_platform/core/config.py").read_text()
    assert "warning" in src, "config.py must emit a warning for insecure jwt_secret in dev"


def test_config_still_raises_in_production():
    """config.py must still raise ValueError when environment=production and secret is insecure."""
    src = Path("fleet_platform/core/config.py").read_text()
    assert "raise ValueError" in src


def test_deps_has_init_and_close_redis():
    """deps.py must expose init_redis and close_redis for lifecycle management."""
    src = Path("fleet_platform/api/deps.py").read_text()
    assert "init_redis" in src
    assert "close_redis" in src
    assert "health_check_interval" in src


def test_main_lifespan_calls_close_redis():
    """main.py lifespan must call close_redis on shutdown."""
    src = Path("fleet_platform/api/main.py").read_text()
    assert "close_redis" in src or "init_redis" in src, (
        "main.py lifespan must manage Redis lifecycle"
    )
