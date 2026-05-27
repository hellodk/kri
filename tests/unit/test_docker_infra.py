"""Unit tests for #123 (log limits) and #114 (DB rename)."""
from pathlib import Path

import yaml  # pyyaml is in dev deps

COMPOSE = Path("deploy/docker-compose.yml")


def test_all_services_have_logging_config():
    content = yaml.safe_load(COMPOSE.read_text())
    services = content.get("services", {})
    for name, svc in services.items():
        assert "logging" in svc, f"Service {name!r} must have logging config"


def test_log_max_size_is_set():
    content = COMPOSE.read_text()
    assert "max-size" in content, "docker-compose must set max-size for log rotation"
    assert "50m" in content, "log max-size must be 50m"


def test_database_not_named_fleet_demo():
    content = COMPOSE.read_text()
    assert "fleet_demo" not in content, "docker-compose must not reference fleet_demo (use fleet_platform)"


def test_config_default_database():
    from fleet_platform.core.config import Settings
    s = Settings(_env_file=None, jwt_secret="a" * 32)
    assert "fleet_demo" not in (s.database_url or ""), "Default database URL must not reference fleet_demo"
