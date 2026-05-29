# tests/unit/test_node_status.py
from datetime import UTC, datetime, timedelta

from fleet_platform.core.auth import hash_password
from fleet_platform.services.node_status import classify_status, verify_node_token


def test_classify_online_within_15_minutes():
    last_seen = datetime.now(UTC) - timedelta(minutes=5)
    assert classify_status(last_seen) == "online"


def test_classify_stale_between_15_and_240_minutes():
    last_seen = datetime.now(UTC) - timedelta(hours=2)
    assert classify_status(last_seen) == "stale"


def test_classify_offline_over_240_minutes():
    last_seen = datetime.now(UTC) - timedelta(hours=5)
    assert classify_status(last_seen) == "offline"


def test_classify_unknown_when_none():
    assert classify_status(None) == "unknown"


def test_classify_boundary_exactly_15_minutes():
    last_seen = datetime.now(UTC) - timedelta(minutes=15, seconds=1)
    assert classify_status(last_seen) == "stale"


def test_verify_node_token_correct_token():
    hashed = hash_password("my-secret-token")
    assert verify_node_token("my-secret-token", hashed) is True


def test_verify_node_token_wrong_token():
    hashed = hash_password("my-secret-token")
    assert verify_node_token("wrong-token", hashed) is False
