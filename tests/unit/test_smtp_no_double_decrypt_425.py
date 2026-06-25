"""#425: get_setting_sync already decrypts; the SMTP send paths must NOT decrypt again.

Regression guard — send_digest/send_alert_email/send_test_email previously called
decrypt_secret() on the already-plaintext password → InvalidToken, breaking all email.

Behavioral approach (#800): instead of scraping the module source for the
forbidden ``decrypt_secret(`` call, we drive every SMTP send path and assert the
EXACT plaintext returned by ``get_setting_sync`` reaches ``_smtp_send`` byte-for-byte.
If any path re-decrypted (the old bug) the password handed to ``_smtp_send`` would
differ from the get_setting_sync return value (or blow up with InvalidToken), so the
equality assertion catches the regression directly.
"""

from contextlib import contextmanager
from unittest.mock import patch

import fleet_platform.services.digest_svc as ds

PLAINTEXT_KEY = "xsmtpsib-PLAINTEXT-already-decrypted"


def _settings(key):
    # mimic get_setting_sync returning ALREADY-DECRYPTED values
    return {
        "smtp_host": "smtp-relay.brevo.com",
        "smtp_port": "587",
        "smtp_username": "user@smtp-brevo.com",
        "smtp_password": PLAINTEXT_KEY,
        "smtp_from": "from@example.com",
        "digest_recipients": "a@example.com",
    }.get(key)


def test_send_test_email_passes_plaintext_password_to_smtp_send():
    captured = {}

    def fake_smtp_send(host, port, user, password, from_addr, recipients, msg):
        captured["password"] = password
        captured["recipients"] = recipients

    with (
        patch.object(ds, "get_setting_sync", side_effect=lambda db, k: _settings(k)),
        patch.object(ds, "_smtp_send", side_effect=fake_smtp_send),
    ):
        result = ds.send_test_email(db=object(), to_addr="x@example.com")

    # The exact plaintext from get_setting_sync must reach _smtp_send — not re-decrypted.
    assert captured["password"] == PLAINTEXT_KEY
    assert result["status"] == "sent"


def test_send_digest_passes_plaintext_password_to_smtp_send():
    """send_digest must hand _smtp_send the plaintext get_setting_sync returns."""
    captured = {}

    def fake_smtp_send(host, port, user, password, from_addr, recipients, msg):
        captured["password"] = password

    with (
        patch.object(ds, "get_setting_sync", side_effect=lambda db, k: _settings(k)),
        patch.object(ds, "_smtp_send", side_effect=fake_smtp_send),
        patch.object(ds, "get_week_stats", return_value={"period_end": "2024-01-07"}),
        patch.object(ds, "render_html", return_value="<html></html>"),
        patch.object(ds, "render_text", return_value="text"),
    ):
        result = ds.send_digest(db=object())

    assert captured["password"] == PLAINTEXT_KEY
    assert result["status"] == "sent"


def test_send_alert_email_passes_plaintext_password_to_smtp_send():
    """send_alert_email must hand _smtp_send the plaintext get_setting_sync returns."""
    captured = {}

    def fake_smtp_send(host, port, user, password, from_addr, recipients, msg):
        captured["password"] = password

    @contextmanager
    def fake_get_sync_db():
        yield object()

    class _Rule:
        event_type = "node_offline"

    class _Event:
        message = "node mm went offline"
        fired_at = None

    with (
        patch("fleet_platform.db.session.get_sync_db", fake_get_sync_db),
        patch.object(ds, "get_setting_sync", side_effect=lambda db, k: _settings(k)),
        patch.object(ds, "_smtp_send", side_effect=fake_smtp_send),
    ):
        ds.send_alert_email(_Rule(), _Event())

    assert captured["password"] == PLAINTEXT_KEY


def test_decrypt_secret_is_never_imported_or_called():
    """The double-decrypt regression re-imported decrypt_secret into digest_svc.

    A behavioral guard: the module namespace must not expose ``decrypt_secret``.
    If a future edit re-introduces the import (the entry point for the #425 bug),
    this fails without scraping source text.
    """
    assert not hasattr(ds, "decrypt_secret"), "digest_svc must not import decrypt_secret (#425 double-decrypt)"
