"""Behavioral tests for #104: alert webhook dispatch on event fire.

These exercise the real ``fleet_platform.services.alert_svc`` functions with a
mocked DB session and a mocked ``urllib.request.urlopen`` so we assert on
*observable behaviour* (payloads sent, timeout used, delivered flag mutated,
SSRF validation outcomes) rather than scraping the source for substrings.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.models.alert import AlertEvent, AlertRule, WebhookConfig
from fleet_platform.services import alert_svc


def _mock_db_returning_webhooks(webhooks: list[WebhookConfig]) -> AsyncMock:
    """Build an AsyncSession mock whose execute(...).scalars().all() == webhooks."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = webhooks
    db.execute = AsyncMock(return_value=result)
    return db


def _make_rule(event_type: str = "node_offline") -> AlertRule:
    rule = AlertRule(name="r", event_type=event_type, enabled=True)
    rule.id = uuid.uuid4()
    return rule


def _make_event(message: str = "Node node-1 offline", node_id: uuid.UUID | None = None) -> AlertEvent:
    return AlertEvent(
        rule_id=uuid.uuid4(),
        node_id=node_id or uuid.uuid4(),
        message=message,
        fired_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        delivered=False,
    )


# ---------------------------------------------------------------------------
# SSRF protection — _validate_webhook_url
# ---------------------------------------------------------------------------


def test_validate_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        alert_svc._validate_webhook_url("ftp://evil.example.com/hook")


def test_validate_rejects_missing_hostname():
    with pytest.raises(ValueError, match="hostname"):
        alert_svc._validate_webhook_url("https://")


def test_validate_rejects_http_for_public_host():
    # A public name over plain HTTP must be rejected (force HTTPS).
    with patch.object(alert_svc.socket, "gethostbyname", return_value="93.184.216.34"):
        with pytest.raises(ValueError, match="https"):
            alert_svc._validate_webhook_url("http://example.com/hook")


def test_validate_allows_https_for_public_host():
    with patch.object(alert_svc.socket, "gethostbyname", return_value="93.184.216.34"):
        # Should not raise.
        alert_svc._validate_webhook_url("https://example.com/hook")


def test_validate_allows_http_for_loopback_name():
    # localhost over HTTP is permitted (local dev webhooks).
    alert_svc._validate_webhook_url("http://localhost:9000/hook")


def test_validate_allows_http_for_private_ip():
    with patch.object(alert_svc.socket, "gethostbyname", return_value="10.0.0.5"):
        alert_svc._validate_webhook_url("http://10.0.0.5/hook")


# ---------------------------------------------------------------------------
# _deliver_alert — generic webhook payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_alert_posts_generic_payload_with_required_fields():
    node_id = uuid.uuid4()
    rule = _make_rule("drift_threshold")
    event = _make_event("drift high", node_id=node_id)
    webhook = WebhookConfig(name="generic", url="https://hooks.example.com/x", type="generic", enabled=True)
    db = _mock_db_returning_webhooks([webhook])

    with (
        patch.object(alert_svc, "_validate_webhook_url"),
        patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()),
        patch.object(alert_svc.urllib.request, "urlopen") as mock_urlopen,
    ):
        await alert_svc._deliver_alert(rule, event, db)

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args.args[0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["event"] == "drift_threshold"
    assert payload["message"] == "drift high"
    assert payload["node_id"] == str(node_id)
    assert payload["fired_at"] == event.fired_at.isoformat()
    assert req.get_method() == "POST"
    assert req.headers.get("Content-type") == "application/json"


@pytest.mark.asyncio
async def test_deliver_alert_uses_timeout():
    rule = _make_rule()
    event = _make_event()
    webhook = WebhookConfig(name="generic", url="https://hooks.example.com/x", type="generic", enabled=True)
    db = _mock_db_returning_webhooks([webhook])

    with (
        patch.object(alert_svc, "_validate_webhook_url"),
        patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()),
        patch.object(alert_svc.urllib.request, "urlopen") as mock_urlopen,
    ):
        await alert_svc._deliver_alert(rule, event, db)

    # urlopen must be called with a positive timeout to avoid hanging the worker.
    assert mock_urlopen.call_args.kwargs.get("timeout") is not None
    assert mock_urlopen.call_args.kwargs["timeout"] > 0


@pytest.mark.asyncio
async def test_deliver_alert_slack_uses_text_field():
    rule = _make_rule()
    event = _make_event("Node down!")
    webhook = WebhookConfig(name="slack", url="https://hooks.slack.com/x", type="slack", enabled=True)
    db = _mock_db_returning_webhooks([webhook])

    with (
        patch.object(alert_svc, "_validate_webhook_url"),
        patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()),
        patch.object(alert_svc.urllib.request, "urlopen") as mock_urlopen,
    ):
        await alert_svc._deliver_alert(rule, event, db)

    payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
    assert "text" in payload
    assert "Node down!" in payload["text"]


@pytest.mark.asyncio
async def test_deliver_alert_sets_delivered_flag_on_success():
    rule = _make_rule()
    event = _make_event()
    assert event.delivered is False
    webhook = WebhookConfig(name="generic", url="https://hooks.example.com/x", type="generic", enabled=True)
    db = _mock_db_returning_webhooks([webhook])

    with (
        patch.object(alert_svc, "_validate_webhook_url"),
        patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()),
        patch.object(alert_svc.urllib.request, "urlopen"),
    ):
        await alert_svc._deliver_alert(rule, event, db)

    assert event.delivered is True


@pytest.mark.asyncio
async def test_deliver_alert_keeps_delivered_false_when_all_fail():
    rule = _make_rule()
    event = _make_event()
    webhook = WebhookConfig(name="generic", url="https://hooks.example.com/x", type="generic", enabled=True)
    db = _mock_db_returning_webhooks([webhook])

    with (
        patch.object(alert_svc, "_validate_webhook_url"),
        patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()),
        patch.object(alert_svc.urllib.request, "urlopen", side_effect=OSError("connection refused")),
    ):
        await alert_svc._deliver_alert(rule, event, db)

    # Delivery failures must be swallowed (never block) and leave delivered False.
    assert event.delivered is False


@pytest.mark.asyncio
async def test_deliver_alert_no_webhooks_sends_nothing():
    rule = _make_rule()
    event = _make_event()
    db = _mock_db_returning_webhooks([])

    with (
        patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()) as mock_email,
        patch.object(alert_svc.urllib.request, "urlopen") as mock_urlopen,
    ):
        await alert_svc._deliver_alert(rule, event, db)

    assert mock_urlopen.call_count == 0
    # With no webhooks the function returns before email dispatch.
    assert mock_email.call_count == 0
    assert event.delivered is False


@pytest.mark.asyncio
async def test_deliver_alert_only_enabled_webhooks_queried():
    """_deliver_alert must filter to enabled webhooks in its query."""
    rule = _make_rule()
    event = _make_event()
    db = _mock_db_returning_webhooks([])

    with patch.object(alert_svc, "_maybe_send_alert_email", new=AsyncMock()):
        await alert_svc._deliver_alert(rule, event, db)

    # The WHERE clause references WebhookConfig.enabled — assert the compiled
    # statement filters on it rather than scraping the source for "enabled".
    stmt = db.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "webhook_configs.enabled" in compiled


# ---------------------------------------------------------------------------
# Check functions invoke _deliver_alert when an event fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_node_offline_fires_and_delivers():
    """_check_node_offline must create an event AND call _deliver_alert for a stale node."""
    rule = _make_rule("node_offline")
    rule.id = uuid.uuid4()
    now = datetime.now(UTC)

    stale_node = MagicMock()
    stale_node.id = uuid.uuid4()
    stale_node.hostname = "web-1"
    stale_node.minion_id = "web-1"
    stale_node.last_seen_at = datetime(2020, 1, 1, tzinfo=UTC)

    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [stale_node]
    dedupe_result = MagicMock()
    dedupe_result.scalar_one_or_none.return_value = None  # not fired recently

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[nodes_result, dedupe_result])
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch.object(alert_svc, "_deliver_alert", new=AsyncMock()) as mock_deliver:
        await alert_svc._check_node_offline(rule, now, db)

    db.add.assert_called_once()
    added_event = db.add.call_args.args[0]
    assert isinstance(added_event, AlertEvent)
    assert added_event.node_id == stale_node.id
    mock_deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_node_offline_skips_when_already_fired():
    """A recently-fired alert must NOT re-deliver (dedup behaviour)."""
    rule = _make_rule("node_offline")
    now = datetime.now(UTC)

    stale_node = MagicMock()
    stale_node.id = uuid.uuid4()
    stale_node.hostname = "web-1"
    stale_node.last_seen_at = datetime(2020, 1, 1, tzinfo=UTC)

    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [stale_node]
    dedupe_result = MagicMock()
    dedupe_result.scalar_one_or_none.return_value = AlertEvent()  # already fired

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[nodes_result, dedupe_result])
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch.object(alert_svc, "_deliver_alert", new=AsyncMock()) as mock_deliver:
        await alert_svc._check_node_offline(rule, now, db)

    db.add.assert_not_called()
    mock_deliver.assert_not_awaited()
