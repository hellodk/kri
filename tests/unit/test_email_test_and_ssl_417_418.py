"""Unit tests for #417 (send_test_email) and #418 (implicit SSL port 465 via _smtp_send)."""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helper — build a minimal stub db for get_setting_sync
# ---------------------------------------------------------------------------


def _make_db_stub(settings: dict[str, str | None]):
    """Return a db-like object where get_setting_sync returns values from `settings`."""
    db = MagicMock()
    # Each call to get_setting_sync(db, key) should return settings.get(key)
    return db, settings


# ---------------------------------------------------------------------------
# _smtp_send — port 465 uses SMTP_SSL, no starttls
# ---------------------------------------------------------------------------


class TestSmtpSend:
    def test_port_465_uses_smtp_ssl(self, monkeypatch):
        """Port 465 must use smtplib.SMTP_SSL, not smtplib.SMTP."""
        mock_ssl_instance = MagicMock()
        mock_ssl_cm = MagicMock()
        mock_ssl_cm.__enter__ = MagicMock(return_value=mock_ssl_instance)
        mock_ssl_cm.__exit__ = MagicMock(return_value=False)
        MockSSL = MagicMock(return_value=mock_ssl_cm)

        mock_plain = MagicMock()
        monkeypatch.setattr(smtplib, "SMTP_SSL", MockSSL)
        monkeypatch.setattr(smtplib, "SMTP", mock_plain)

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", 465, "user", "pass", "from@x.com", ["to@x.com"], msg)

        # SMTP_SSL must be called
        MockSSL.assert_called_once()
        # Plain SMTP must NOT be called
        mock_plain.assert_not_called()

    def test_port_465_no_starttls_called(self, monkeypatch):
        """SMTP_SSL path must NOT call starttls()."""
        mock_ssl_instance = MagicMock()
        mock_ssl_cm = MagicMock()
        mock_ssl_cm.__enter__ = MagicMock(return_value=mock_ssl_instance)
        mock_ssl_cm.__exit__ = MagicMock(return_value=False)
        MockSSL = MagicMock(return_value=mock_ssl_cm)
        monkeypatch.setattr(smtplib, "SMTP_SSL", MockSSL)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock())

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", 465, "user", "pass", "from@x.com", ["to@x.com"], msg)

        mock_ssl_instance.starttls.assert_not_called()

    def test_port_587_uses_plain_smtp_and_starttls(self, monkeypatch):
        """Port 587 must use smtplib.SMTP and call starttls()."""
        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        MockSMTP = MagicMock(return_value=mock_cm)

        mock_ssl = MagicMock()
        monkeypatch.setattr(smtplib, "SMTP", MockSMTP)
        monkeypatch.setattr(smtplib, "SMTP_SSL", mock_ssl)

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", 587, "user", "pass", "from@x.com", ["to@x.com"], msg)

        MockSMTP.assert_called_once()
        mock_ssl.assert_not_called()
        mock_instance.starttls.assert_called_once()

    def test_login_called_when_user_and_password(self, monkeypatch):
        """login() must be called when both user and password are provided (587 path)."""
        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock(return_value=mock_cm))

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", 587, "user@x.com", "secret", "from@x.com", ["to@x.com"], msg)

        mock_instance.login.assert_called_once_with("user@x.com", "secret")

    def test_login_called_ssl_when_user_and_password(self, monkeypatch):
        """login() must be called on the SSL path too when credentials are provided."""
        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(smtplib, "SMTP_SSL", MagicMock(return_value=mock_cm))
        monkeypatch.setattr(smtplib, "SMTP", MagicMock())

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", 465, "user@x.com", "secret", "from@x.com", ["to@x.com"], msg)

        mock_instance.login.assert_called_once_with("user@x.com", "secret")

    def test_login_not_called_when_no_credentials(self, monkeypatch):
        """login() must NOT be called when user/password are empty."""
        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock(return_value=mock_cm))

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", 587, "", "", "from@x.com", ["to@x.com"], msg)

        mock_instance.login.assert_not_called()

    def test_port_as_string_coerced_to_int(self, monkeypatch):
        """Port value passed as a string '465' must still trigger SMTP_SSL path."""
        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        MockSSL = MagicMock(return_value=mock_cm)
        monkeypatch.setattr(smtplib, "SMTP_SSL", MockSSL)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock())

        from fleet_platform.services.digest_svc import _smtp_send

        msg = MagicMock()
        msg.as_string.return_value = "MSG"
        _smtp_send("smtp.example.com", "465", "u", "p", "from@x.com", ["to@x.com"], msg)  # type: ignore[arg-type]

        MockSSL.assert_called_once()


# ---------------------------------------------------------------------------
# send_test_email
# ---------------------------------------------------------------------------

_SMTP_SETTINGS = {
    "smtp_host": "smtp.example.com",
    "smtp_port": "587",
    "smtp_username": "user@x.com",
    "smtp_password": None,
    "smtp_from": "kri@x.com",
    "digest_recipients": "admin@x.com, ops@x.com",
}


def _patch_get_setting_sync(monkeypatch, settings: dict):
    """Monkeypatch get_setting_sync in digest_svc to return from `settings` dict keyed by constant value."""
    # The constants in platform_settings_svc are string literals
    from fleet_platform.services import platform_settings_svc as pss

    setting_key_map = {
        pss.SMTP_HOST: settings.get("smtp_host"),
        pss.SMTP_PORT: settings.get("smtp_port"),
        pss.SMTP_USERNAME: settings.get("smtp_username"),
        pss.SMTP_PASSWORD: settings.get("smtp_password"),
        pss.SMTP_FROM: settings.get("smtp_from"),
        pss.DIGEST_RECIPIENTS: settings.get("digest_recipients"),
    }

    def fake_get_setting_sync(db, key):
        return setting_key_map.get(key)

    monkeypatch.setattr(
        "fleet_platform.services.digest_svc.get_setting_sync",
        fake_get_setting_sync,
    )
    # NOTE: digest_svc no longer calls decrypt_secret — get_setting_sync already
    # returns decrypted values; the old double-decrypt was the #425 bug.


class TestSendTestEmail:
    def test_returns_sent_for_configured_host_and_recipient(self, monkeypatch):
        """Returns {'status':'sent', 'recipients': N} when SMTP is configured."""
        _patch_get_setting_sync(monkeypatch, _SMTP_SETTINGS)

        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock(return_value=mock_cm))

        from fleet_platform.services.digest_svc import send_test_email

        db = MagicMock()
        result = send_test_email(db)

        assert result["status"] == "sent"
        assert result["recipients"] == 2  # admin@x.com + ops@x.com

    def test_raises_value_error_when_no_host(self, monkeypatch):
        """Raises ValueError('SMTP host not configured') when smtp_host is empty."""
        settings = {**_SMTP_SETTINGS, "smtp_host": None}
        _patch_get_setting_sync(monkeypatch, settings)

        from fleet_platform.services.digest_svc import send_test_email

        db = MagicMock()
        with pytest.raises(ValueError, match="SMTP host not configured"):
            send_test_email(db)

    def test_raises_value_error_when_no_recipients(self, monkeypatch):
        """Raises ValueError when no recipients and no to_addr provided."""
        settings = {**_SMTP_SETTINGS, "digest_recipients": ""}
        _patch_get_setting_sync(monkeypatch, settings)

        from fleet_platform.services.digest_svc import send_test_email

        db = MagicMock()
        with pytest.raises(ValueError, match="No recipient"):
            send_test_email(db)

    def test_to_addr_override_takes_precedence(self, monkeypatch):
        """When to_addr is passed, it overrides the configured digest_recipients."""
        settings = {**_SMTP_SETTINGS, "digest_recipients": ""}
        _patch_get_setting_sync(monkeypatch, settings)

        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock(return_value=mock_cm))

        from fleet_platform.services.digest_svc import send_test_email

        db = MagicMock()
        result = send_test_email(db, to_addr="custom@example.com")

        assert result["status"] == "sent"
        assert result["recipients"] == 1

    def test_sendmail_called_with_correct_recipients(self, monkeypatch):
        """sendmail() is called with the expected recipient list."""
        _patch_get_setting_sync(monkeypatch, _SMTP_SETTINGS)

        mock_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(smtplib, "SMTP", MagicMock(return_value=mock_cm))

        from fleet_platform.services.digest_svc import send_test_email

        db = MagicMock()
        send_test_email(db, to_addr="specific@example.com")

        # sendmail should have been called with our specific address
        args = mock_instance.sendmail.call_args
        assert args is not None
        recipients_arg = args[0][1]  # positional arg index 1
        assert "specific@example.com" in recipients_arg


# ---------------------------------------------------------------------------
# Source-contract tests — confirm route + import exist
# ---------------------------------------------------------------------------


class TestSourceContracts:
    def test_platform_settings_has_test_email_route(self):
        """platform_settings.py router must have a /test-email route."""
        from fleet_platform.api.routes.platform_settings import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/settings/test-email" in paths

    def test_platform_settings_imports_send_test_email(self):
        """send_test_email must be importable from digest_svc via platform_settings."""
        # This confirms the import exists and doesn't crash
        import fleet_platform.api.routes.platform_settings as mod  # noqa: F401
        from fleet_platform.services.digest_svc import send_test_email  # noqa: F401

        assert callable(send_test_email)

    def test_settings_page_has_send_test_email_text(self):
        """SettingsPage.tsx must contain 'Send test email' text."""
        import pathlib

        path = pathlib.Path(__file__).parent.parent.parent / "frontend" / "src" / "pages" / "SettingsPage.tsx"
        content = path.read_text()
        assert "Send test email" in content or "test-email" in content, (
            "SettingsPage.tsx must reference 'Send test email' or 'test-email'"
        )
