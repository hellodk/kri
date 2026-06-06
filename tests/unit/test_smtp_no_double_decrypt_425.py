"""#425: get_setting_sync already decrypts; the SMTP send paths must NOT decrypt again.

Regression guard — send_digest/send_alert_email/send_test_email previously called
decrypt_secret() on the already-plaintext password → InvalidToken, breaking all email.
"""

from pathlib import Path
from unittest.mock import patch

import fleet_platform.services.digest_svc as ds

SRC = Path(ds.__file__).read_text()
PLAINTEXT_KEY = "xsmtpsib-PLAINTEXT-already-decrypted"


def test_no_decrypt_secret_double_call_in_source():
    # The double-decrypt pattern must be gone everywhere in the module.
    assert "decrypt_secret(smtp_password_raw)" not in SRC
    assert "decrypt_secret(" not in SRC  # no remaining (mis)use at all


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
