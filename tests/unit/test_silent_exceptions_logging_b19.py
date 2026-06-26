"""Tests for silent exception logging fixes — issue #66."""

import logging


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
