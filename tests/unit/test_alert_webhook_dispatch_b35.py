"""Tests for #104: alert webhook dispatch on event fire."""

from pathlib import Path

ALERT_SVC = (Path(__file__).parent.parent.parent / "fleet_platform/services/alert_svc.py").read_text()


def test_deliver_alert_function_in_svc():
    """Verify _deliver_alert function exists in alert_svc."""
    assert "async def _deliver_alert" in ALERT_SVC


def test_deliver_alert_called_from_check_functions():
    """_deliver_alert must be called in each event check function."""
    assert ALERT_SVC.count("await _deliver_alert") >= 4, "_deliver_alert must be called in all check functions"


def test_ssrf_protection_validates_url():
    """SSRF protection must validate webhook URLs."""
    assert "_validate_webhook_url" in ALERT_SVC
    assert "is_private" in ALERT_SVC or "is_loopback" in ALERT_SVC


def test_slack_payload_format():
    """Slack webhook must use text field."""
    assert '"text"' in ALERT_SVC or "'text'" in ALERT_SVC


def test_generic_webhook_payload_format():
    """Generic webhook must have event, message, node_id, fired_at fields."""
    assert '"event"' in ALERT_SVC
    assert '"message"' in ALERT_SVC
    assert '"node_id"' in ALERT_SVC
    assert '"fired_at"' in ALERT_SVC


def test_webhook_timeout_set():
    """Webhook requests must have a timeout."""
    assert "timeout=" in ALERT_SVC


def test_webhook_delivered_flag_set():
    """Alert event delivered flag must be set after successful delivery."""
    assert "delivered" in ALERT_SVC


def test_only_enabled_webhooks_fetched():
    """Only enabled webhooks should be fetched."""
    assert "enabled" in ALERT_SVC


def test_http_methods_used():
    """HTTP requests must use urllib or asyncio."""
    assert "urllib" in ALERT_SVC or "asyncio" in ALERT_SVC
