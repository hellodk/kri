"""Tests for #110: Salt ZeroMQ ports must not be bound to all interfaces.

Ports 4505/4506 should use ${SALT_BIND_IP} so operators can restrict them
to a specific interface (e.g. Tailscale) without hardcoding an IP.
"""
from pathlib import Path

COMPOSE = Path("deploy/docker-compose.yml").read_text()


def test_salt_zmq_publisher_uses_bind_ip():
    assert '"4505:4505"' not in COMPOSE, (
        "Salt ZeroMQ publisher port must bind via ${SALT_BIND_IP:-0.0.0.0}:4505:4505"
    )
    assert "${SALT_BIND_IP" in COMPOSE


def test_salt_zmq_request_uses_bind_ip():
    assert '"4506:4506"' not in COMPOSE, (
        "Salt ZeroMQ request port must bind via ${SALT_BIND_IP:-0.0.0.0}:4506:4506"
    )
    assert "${SALT_BIND_IP" in COMPOSE


def test_salt_bind_ip_has_safe_default():
    assert "${SALT_BIND_IP:-0.0.0.0}" in COMPOSE
