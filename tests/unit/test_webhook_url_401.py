"""Unit tests for webhook URL validation (#401 — HTTPS-only enforcement)."""

import pytest

from fleet_platform.services.alert_svc import _validate_webhook_url


class TestWebhookUrlScheme:
    """Test HTTPS scheme enforcement with exceptions for loopback/private IPs."""

    def test_https_public_url_accepted(self):
        """https://example.com should be accepted."""
        _validate_webhook_url("https://example.com/webhook")
        # No exception raised — test passes

    def test_http_public_url_rejected(self):
        """http://example.com should be rejected."""
        with pytest.raises(ValueError, match="https only"):
            _validate_webhook_url("http://example.com/webhook")

    def test_http_localhost_accepted(self):
        """http://localhost should be accepted for local dev."""
        _validate_webhook_url("http://localhost:8080/webhook")
        # No exception raised

    def test_http_127_0_0_1_accepted(self):
        """http://127.0.0.1 should be accepted for local dev."""
        _validate_webhook_url("http://127.0.0.1:9000/webhook")
        # No exception raised

    def test_http_10_network_accepted(self):
        """http://10.x.x.x should be accepted (RFC 1918 private)."""
        _validate_webhook_url("http://10.0.0.1:5000/webhook")
        # No exception raised

    def test_http_172_16_network_accepted(self):
        """http://172.16.x.x should be accepted (RFC 1918 private)."""
        _validate_webhook_url("http://172.16.0.1:5000/webhook")
        # No exception raised

    def test_http_192_168_network_accepted(self):
        """http://192.168.x.x should be accepted (RFC 1918 private)."""
        _validate_webhook_url("http://192.168.1.1:5000/webhook")
        # No exception raised

    def test_invalid_scheme_rejected(self):
        """ftp:// scheme should be rejected."""
        with pytest.raises(ValueError, match="Invalid webhook URL scheme"):
            _validate_webhook_url("ftp://example.com/webhook")

    def test_https_with_private_ip_accepted(self):
        """https://192.168.1.1 should be accepted (always safe)."""
        _validate_webhook_url("https://192.168.1.1:443/webhook")
        # No exception raised
