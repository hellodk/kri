"""Unit tests for #160 (Docker healthchecks) and #154 (security pagination)."""

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("deploy/docker-compose.yml").read_text())
SECURITY = Path("fleet_platform/api/routes/security.py").read_text()


def test_api_service_has_healthcheck():
    assert "healthcheck" in COMPOSE["services"]["api"], "api service must have a healthcheck"
    hc = COMPOSE["services"]["api"]["healthcheck"]
    assert hc.get("test") and "/health/ready" in str(hc["test"]), "api healthcheck must call /health/ready"


def test_worker_service_has_healthcheck():
    assert "healthcheck" in COMPOSE["services"]["worker"], "worker service must have a healthcheck"


def test_beat_service_has_healthcheck():
    assert "healthcheck" in COMPOSE["services"]["beat"], "beat service must have a healthcheck"


def test_frontend_service_has_healthcheck():
    assert "healthcheck" in COMPOSE["services"]["frontend"], "frontend service must have a healthcheck"


def test_security_node_list_has_pagination():
    assert "per_page" in SECURITY, "security_node_list must support per_page param"
    assert "offset" in SECURITY or "skip" in SECURITY, "security_node_list must use offset/skip for pagination"
