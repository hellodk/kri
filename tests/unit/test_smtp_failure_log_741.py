"""#741: SMTP send failures must be logged at WARNING, not silently swallowed."""

import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from fleet_platform.models.pending_action import PendingAction


def _smtp_settings(key: str):
    return {
        "smtp_host": "smtp.example.com",
        "smtp_port": "587",
        "smtp_username": "user@example.com",
        "smtp_password": "",
        "smtp_from": "kri@example.com",
        "digest_recipients": "admin@example.com",
        "kri_api_url": "http://localhost",
    }.get(key)


@contextmanager
def _fake_sync_db():
    yield MagicMock()


@pytest.mark.asyncio
async def test_send_approval_email_logs_smtp_failure(caplog):
    """SMTP errors in _send_approval_email must emit a WARNING log."""
    from fleet_platform.services import pending_action_svc

    action_id = uuid.uuid4()
    action = PendingAction(
        id=action_id,
        node_id=uuid.uuid4(),
        action_type="process_stop",
        status="pending",
        approval_token="test-token",
        expires_at=datetime.now(UTC),
    )
    node = MagicMock()
    node.hostname = "test-node"
    node.minion_id = "test.minion"

    class _FailingSMTP:
        def __init__(self, *args, **kwargs):
            raise OSError("connection refused")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with (
        patch("fleet_platform.db.session.get_sync_db", side_effect=_fake_sync_db),
        patch(
            "fleet_platform.services.platform_settings_svc.get_setting_sync",
            side_effect=lambda db, k: _smtp_settings(k),
        ),
        patch("smtplib.SMTP", _FailingSMTP),
        caplog.at_level(logging.WARNING, logger="fleet_platform.services.pending_action_svc"),
    ):
        await pending_action_svc._send_approval_email(action, node, "operator@example.com")

    smtp_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == "fleet_platform.services.pending_action_svc"
        and "approval email" in r.message
    ]
    assert smtp_warnings, "Expected a WARNING log when SMTP send fails"
    assert str(action_id) in smtp_warnings[0].message
