"""Tests for #110: Salt ZeroMQ ports must not be exposed in Docker compose.

salt-master now runs natively on mm1 — there are no salt ports in docker-compose.
Ports 4505/4506 are managed by the launchd service on mm1, not Docker.
"""
from pathlib import Path

COMPOSE = Path("deploy/docker-compose.yml").read_text()


def test_salt_zmq_publisher_not_in_compose():
    """Port 4505 must not be exposed in docker-compose — salt-master is on mm1."""
    assert '"4505:4505"' not in COMPOSE, (
        "Salt ZeroMQ publisher port 4505 should NOT be in docker-compose — "
        "salt-master runs natively on mm1, not in Docker."
    )


def test_salt_zmq_request_not_in_compose():
    """Port 4506 must not be exposed in docker-compose — salt-master is on mm1."""
    assert '"4506:4506"' not in COMPOSE, (
        "Salt ZeroMQ request port 4506 should NOT be in docker-compose — "
        "salt-master runs natively on mm1, not in Docker."
    )


def test_salt_master_removed_from_compose():
    """Verify salt-master service was removed from docker-compose."""
    import yaml
    compose = yaml.safe_load(COMPOSE)
    assert "salt-master" not in compose.get("services", {}), (
        "salt-master service must not be in docker-compose — it runs on mm1 natively."
    )


def test_salt_api_url_configured_via_env():
    """Worker must configure SALT_API_URL from environment, not hardcoded."""
    assert "SALT_API_URL" in COMPOSE, (
        "Worker must reference SALT_API_URL env var to reach mm1 salt-api"
    )
