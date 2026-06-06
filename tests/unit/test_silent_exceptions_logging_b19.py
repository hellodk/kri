"""Tests for silent exception logging fixes — issues #63 and #66."""

import logging
from unittest.mock import MagicMock, patch


class TestGetNodeCredentialsLogging:
    """Tests for _get_node_credentials in ansible_tasks.py (issue #63)."""

    def test_get_node_credentials_logs_on_decrypt_failure(self, caplog):
        """Decrypt failure must emit a WARNING log — not silently swallow."""
        from fleet_platform.workers.ansible_tasks import _get_node_credentials

        node = MagicMock()
        node.id = "test-node-id-123"
        node.ssh_username = ""
        node.ssh_password_enc = "bad-encrypted-value"
        node.ssh_auth_mode = "password"

        with patch(
            "fleet_platform.services.platform_settings_svc.decrypt_secret",
            side_effect=Exception("bad key"),
        ):
            with caplog.at_level(logging.WARNING, logger="fleet_platform.workers.ansible_tasks"):
                result = _get_node_credentials(node)

        # Must not crash
        assert result is not None
        # Must emit at least one WARNING
        assert any(r.levelno == logging.WARNING for r in caplog.records), "Expected a WARNING log when decryption fails"
        # Log must mention the node id
        warning_text = " ".join(r.message for r in caplog.records if r.levelno == logging.WARNING)
        assert "test-node-id-123" in warning_text

    def test_get_node_credentials_returns_empty_password_on_failure(self):
        """On decrypt failure, password must be empty string — no crash."""
        from fleet_platform.workers.ansible_tasks import _get_node_credentials

        node = MagicMock()
        node.id = "test-node-id-456"
        node.ssh_username = ""
        node.ssh_password_enc = "bad-encrypted-value"
        node.ssh_auth_mode = "password"

        with patch(
            "fleet_platform.services.platform_settings_svc.decrypt_secret",
            side_effect=Exception("bad key"),
        ):
            user, password, auth_mode = _get_node_credentials(node)

        assert user == ""
        assert password == ""
        assert auth_mode == "password"


class TestWebSSHLogger:
    """Tests for logger in webssh.py (issue #66)."""

    def test_webssh_logger_exists(self):
        """webssh module must expose a module-level logger instance."""
        import fleet_platform.api.routes.webssh as webssh_module

        assert hasattr(webssh_module, "logger"), (
            "fleet_platform.api.routes.webssh must have a module-level 'logger' attribute"
        )
        assert isinstance(webssh_module.logger, logging.Logger), "webssh.logger must be a logging.Logger instance"

    def test_webssh_send_to_browser_logs_on_send_failure(self, caplog):
        """logger.debug fires when ws.send_text raises."""
        import asyncio
        import uuid
        from unittest.mock import AsyncMock, MagicMock

        from fleet_platform.api.routes.webssh import SSHProxySession

        ws = MagicMock()
        ws.send_text = AsyncMock(side_effect=Exception("connection reset"))
        proxy = SSHProxySession(ws=ws, session_id=uuid.uuid4())
        # Stub out _flush_recording so it doesn't try to hit the DB
        proxy._flush_recording = AsyncMock()

        with caplog.at_level(logging.DEBUG, logger="fleet_platform.api.routes.webssh"):
            asyncio.run(proxy.send_to_browser(b"hello"))

        assert any("send_to_browser" in r.message for r in caplog.records), (
            "logger.debug must fire in send_to_browser when ws.send_text raises"
        )
