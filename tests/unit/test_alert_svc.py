# tests/unit/test_alert_svc.py
import socket
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.alert_svc import (
    _check_drift_threshold,
    _check_key_pending,
    _validate_webhook_url,
    evaluate_alerts,
)


# ---------------------------------------------------------------------------
# _validate_webhook_url — pure function, no async, no DB
# ---------------------------------------------------------------------------


def test_validate_webhook_url_valid_https():
    with patch("socket.gethostbyname", return_value="1.1.1.1"):
        _validate_webhook_url("https://hooks.example.com/webhook")  # must not raise


def test_validate_webhook_url_invalid_scheme():
    with pytest.raises(ValueError, match="scheme"):
        _validate_webhook_url("ftp://hooks.example.com/webhook")


def test_validate_webhook_url_private_ip():
    with patch("socket.gethostbyname", return_value="192.168.1.1"):
        with pytest.raises(ValueError, match="private"):
            _validate_webhook_url("https://internal.example.com/webhook")


def test_validate_webhook_url_loopback():
    with patch("socket.gethostbyname", return_value="127.0.0.1"):
        with pytest.raises(ValueError):
            _validate_webhook_url("https://localhost/webhook")


def test_validate_webhook_url_link_local():
    with patch("socket.gethostbyname", return_value="169.254.1.1"):
        with pytest.raises(ValueError):
            _validate_webhook_url("https://link-local.example.com/webhook")


def test_validate_webhook_url_dns_failure():
    with patch("socket.gethostbyname", side_effect=socket.gaierror("no such host")):
        _validate_webhook_url("https://unresolvable.example.com/webhook")  # must not raise


def test_validate_webhook_url_no_hostname():
    with pytest.raises(ValueError, match="hostname"):
        _validate_webhook_url("https://")


# ---------------------------------------------------------------------------
# evaluate_alerts
# ---------------------------------------------------------------------------


async def test_evaluate_alerts_no_rules():
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    db.execute.return_value = exec_result

    await evaluate_alerts(db)

    db.commit.assert_not_called()


async def test_evaluate_alerts_calls_check_for_each_type():
    db = AsyncMock()

    rule_offline = MagicMock()
    rule_offline.event_type = "node_offline"
    rule_drift = MagicMock()
    rule_drift.event_type = "drift_threshold"
    rule_cve = MagicMock()
    rule_cve.event_type = "cve_found"
    rule_key = MagicMock()
    rule_key.event_type = "key_pending"

    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [
        rule_offline, rule_drift, rule_cve, rule_key
    ]
    db.execute.return_value = exec_result

    with (
        patch("fleet_platform.services.alert_svc._check_node_offline", new=AsyncMock()) as mock_offline,
        patch("fleet_platform.services.alert_svc._check_drift_threshold", new=AsyncMock()) as mock_drift,
        patch("fleet_platform.services.alert_svc._check_cve_found", new=AsyncMock()) as mock_cve,
        patch("fleet_platform.services.alert_svc._check_key_pending", new=AsyncMock()) as mock_key,
    ):
        await evaluate_alerts(db)

        mock_offline.assert_called_once()
        mock_drift.assert_called_once()
        mock_cve.assert_called_once()
        mock_key.assert_called_once()


# ---------------------------------------------------------------------------
# _check_drift_threshold
# ---------------------------------------------------------------------------


async def test_check_drift_threshold_no_threshold():
    db = AsyncMock()
    rule = MagicMock()
    rule.threshold = None
    now = datetime.now(UTC)

    await _check_drift_threshold(rule, now, db)

    db.execute.assert_not_called()


async def test_check_drift_threshold_fires_event():
    db = AsyncMock()
    rule = MagicMock()
    rule.id = uuid.uuid4()
    rule.threshold = 50.0
    now = datetime.now(UTC)

    node = MagicMock()
    node.id = uuid.uuid4()
    node.hostname = "mac-builder-01"
    node.minion_id = "mac-builder-01"
    node.drift_score = 75.0

    # Call 1: nodes exceeding threshold
    result_nodes = MagicMock()
    result_nodes.scalars.return_value.all.return_value = [node]

    # Call 2: existing event check → None means no recent event
    result_no_event = MagicMock()
    result_no_event.scalar_one_or_none.return_value = None

    # Call 3: _deliver_alert fetches webhooks → empty list
    result_no_webhooks = MagicMock()
    result_no_webhooks.scalars.return_value.all.return_value = []

    db.execute.side_effect = [result_nodes, result_no_event, result_no_webhooks]

    await _check_drift_threshold(rule, now, db)

    db.add.assert_called_once()
    added_event = db.add.call_args[0][0]
    assert added_event.rule_id == rule.id
    assert added_event.node_id == node.id
    assert added_event.delivered is False


# ---------------------------------------------------------------------------
# _check_key_pending
# ---------------------------------------------------------------------------


async def test_check_key_pending_no_dir():
    db = AsyncMock()
    rule = MagicMock()
    now = datetime.now(UTC)

    with patch("os.listdir", side_effect=OSError("no such directory")):
        await _check_key_pending(rule, now, db)

    db.add.assert_not_called()


async def test_check_key_pending_empty_dir():
    db = AsyncMock()
    rule = MagicMock()
    now = datetime.now(UTC)

    with patch("os.listdir", return_value=[]):
        await _check_key_pending(rule, now, db)

    db.add.assert_not_called()


async def test_check_key_pending_fires_event():
    db = AsyncMock()
    rule = MagicMock()
    rule.id = uuid.uuid4()
    now = datetime.now(UTC)

    # Call 1: existing event check → None means no recent firing
    result_no_event = MagicMock()
    result_no_event.scalar_one_or_none.return_value = None

    # Call 2: _deliver_alert fetches webhooks → empty list
    result_no_webhooks = MagicMock()
    result_no_webhooks.scalars.return_value.all.return_value = []

    db.execute.side_effect = [result_no_event, result_no_webhooks]

    with patch("os.listdir", return_value=["minion1", "minion2"]):
        await _check_key_pending(rule, now, db)

    db.add.assert_called_once()
    added_event = db.add.call_args[0][0]
    assert added_event.rule_id == rule.id
    assert added_event.node_id is None
    assert added_event.delivered is False
    assert "2" in added_event.message
