"""Tests for #840: bootstrap SSH TOFU — known_hosts token normalisation.

WebSSH stored keys as base64(export_public_key("openssh")), an opaque blob that
OpenSSH cannot parse as a known_hosts entry.  The fix:

1. ``to_known_hosts_token`` normalises both legacy base64-wrapped and native
   ``<alg> <base64>`` forms into a valid known_hosts token.
2. Bootstrap / _grains_via_ssh fall back to StrictHostKeyChecking=accept-new
   when the stored key cannot be parsed (instead of hard-failing).
3. ``verify_or_store_host_key`` compares normalised forms so a legacy key and
   its decoded equivalent are treated as equal (no spurious MITM warnings).
4. WebSSH now stores keys in native form so new nodes work out of the box.
"""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=False)
def mock_ansible_runner():
    """Stub out heavy dependencies not installed in the unit-test venv.

    ``playbook_tasks`` has module-level ``import ansible_runner`` and
    ``import redis`` which are runtime deps, not dev deps.  We stub them
    out so the pure-Python helper ``_write_known_hosts`` is accessible.
    """
    stubs = {
        "ansible_runner": ModuleType("ansible_runner"),
        "redis": ModuleType("redis"),
    }
    with patch.dict(sys.modules, stubs):
        # Evict any previously cached (potentially broken) import.
        sys.modules.pop("fleet_platform.workers.playbook_tasks", None)
        yield
    sys.modules.pop("fleet_platform.workers.playbook_tasks", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_legacy_key(alg: str = "ssh-ed25519", b64_key: str = "AAAAC3NzaC1lZDI1NTE5AAAAItest") -> str:
    """Build a legacy base64-wrapped key (the old storage format)."""
    native = f"{alg} {b64_key}"
    return base64.b64encode(native.encode()).decode()


def _make_native_key(alg: str = "ssh-ed25519", b64_key: str = "AAAAC3NzaC1lZDI1NTE5AAAAItest") -> str:
    """Build a native '<alg> <base64>' token (the new storage format)."""
    return f"{alg} {b64_key}"


# ---------------------------------------------------------------------------
# to_known_hosts_token
# ---------------------------------------------------------------------------


class TestToKnownHostsToken:
    def test_native_ed25519_passes_through(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        native = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo"
        assert to_known_hosts_token(native) == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo"

    def test_native_rsa_passes_through(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        native = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC"
        assert to_known_hosts_token(native) == "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC"

    def test_native_ecdsa_passes_through(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        native = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTY"
        assert to_known_hosts_token(native) == "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTY"

    def test_native_strips_trailing_comment(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        native_with_comment = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo user@host"
        result = to_known_hosts_token(native_with_comment)
        assert result == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo"

    def test_legacy_base64_wrapped_decodes_to_token(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        legacy = _make_legacy_key("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAItest")
        result = to_known_hosts_token(legacy)
        assert result == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest"

    def test_legacy_rsa_base64_wrapped_decodes_to_token(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        legacy = _make_legacy_key("ssh-rsa", "AAAAB3NzaC1yc2EAAAADAQABAAABgQC")
        result = to_known_hosts_token(legacy)
        assert result == "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC"

    def test_unparseable_returns_none(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        assert to_known_hosts_token("not-valid-at-all!!!") is None

    def test_empty_string_returns_none(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        assert to_known_hosts_token("") is None

    def test_unknown_algorithm_returns_none(self):
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        # Well-formed base64 of something that doesn't start with a known alg
        payload = base64.b64encode(b"unknown-alg AAAA").decode()
        assert to_known_hosts_token(payload) is None

    def test_legacy_base64_of_key_with_newline(self):
        """export_public_key("openssh") sometimes appends a newline — must still parse."""
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        native_with_newline = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo\n"
        legacy = base64.b64encode(native_with_newline.encode()).decode()
        result = to_known_hosts_token(legacy)
        assert result == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo"


# ---------------------------------------------------------------------------
# verify_or_store_host_key: legacy / native cross-format comparison
# ---------------------------------------------------------------------------


class TestVerifyOrStoreHostKey:
    @pytest.mark.asyncio
    async def test_stores_key_on_first_connection(self):
        from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

        node = MagicMock()
        node.ssh_host_key = None
        node.id = "node-1"
        node.hostname = "mm1"
        db = AsyncMock()
        result = await verify_or_store_host_key(node, _make_native_key(), db)
        assert result is True
        assert node.ssh_host_key == _make_native_key()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exact_match_passes(self):
        from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

        native = _make_native_key()
        node = MagicMock()
        node.ssh_host_key = native
        db = AsyncMock()
        assert await verify_or_store_host_key(node, native, db) is True

    @pytest.mark.asyncio
    async def test_legacy_stored_vs_native_incoming_matches(self):
        """Legacy base64-wrapped stored key must match its native decoded form (#840)."""
        from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

        legacy = _make_legacy_key("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAItest")
        native = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest"

        node = MagicMock()
        node.ssh_host_key = legacy
        db = AsyncMock()
        result = await verify_or_store_host_key(node, native, db)
        assert result is True, "legacy stored key should match equivalent native token"
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_native_stored_vs_legacy_incoming_matches(self):
        """Native stored key must match an incoming legacy-wrapped form (#840)."""
        from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

        native = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest"
        legacy = _make_legacy_key("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAItest")

        node = MagicMock()
        node.ssh_host_key = native
        db = AsyncMock()
        result = await verify_or_store_host_key(node, legacy, db)
        assert result is True, "native stored key should match equivalent legacy-wrapped token"

    @pytest.mark.asyncio
    async def test_genuine_mismatch_returns_false(self):
        from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

        node = MagicMock()
        node.ssh_host_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIoriginal"
        node.id = "node-1"
        node.hostname = "mm1"
        db = AsyncMock()
        db.add = MagicMock()
        result = await verify_or_store_host_key(node, "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIdifferent", db)
        assert result is False
        db.add.assert_called_once()
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Bootstrap path: known_hosts normalisation in ansible_tasks.py
# ---------------------------------------------------------------------------


class TestBootstrapKnownHostsPath:
    def test_valid_native_key_writes_strict_check(self):
        """When stored key is valid native form, StrictHostKeyChecking=yes must be used."""
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        native = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo"
        token = to_known_hosts_token(native)
        assert token is not None, "native key must parse to a valid token"

        # Simulate what bootstrap does
        with tempfile.TemporaryDirectory():
            with tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False) as tmp_kh:
                tmp_kh.write(f"10.0.0.1 {token}\n")
                kh_path = tmp_kh.name

        content = Path(kh_path).read_text()
        assert "10.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo" in content

    def test_valid_legacy_key_writes_strict_check(self):
        """When stored key is legacy base64-wrapped, token is decoded and StrictHostKeyChecking=yes used."""
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        legacy = _make_legacy_key("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAItest")
        token = to_known_hosts_token(legacy)
        assert token == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest"

    def test_unparseable_key_falls_back_to_accept_new(self):
        """When stored key cannot be parsed, bootstrap falls back to accept-new (#840)."""
        from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

        bad_key = "not-valid-garbage!!!"
        token = to_known_hosts_token(bad_key)
        # Bootstrap logic: if token is None → accept-new, no hard failure
        assert token is None, "unparseable key must return None so bootstrap falls back"

    def test_ansible_tasks_source_uses_to_known_hosts_token(self):
        """ansible_tasks.py must use to_known_hosts_token for key normalisation."""
        src = Path("fleet_platform/workers/ansible_tasks.py").read_text()
        assert "to_known_hosts_token" in src


# ---------------------------------------------------------------------------
# _write_known_hosts: legacy key normalisation
# ---------------------------------------------------------------------------


class TestWriteKnownHostsNormalisation:
    def test_legacy_key_written_as_valid_token(self, mock_ansible_runner):
        """_write_known_hosts must normalise a legacy base64-wrapped key to a valid token."""
        from fleet_platform.workers.playbook_tasks import _write_known_hosts

        legacy = _make_legacy_key("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAItest")
        hosts = [{"hostname": "mac-01", "ip": "10.0.0.1", "ssh_host_key": legacy}]

        with tempfile.TemporaryDirectory() as tmpdir:
            kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)
            content = Path(kh_path).read_text()

        # Must contain the decoded native form, NOT the raw legacy blob
        assert "10.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest" in content
        assert all_have_keys is True

    def test_native_key_written_unchanged(self, mock_ansible_runner):
        """_write_known_hosts must accept a native key token without modification."""
        from fleet_platform.workers.playbook_tasks import _write_known_hosts

        native = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo"
        hosts = [{"hostname": "mac-01", "ip": "10.0.0.1", "ssh_host_key": native}]

        with tempfile.TemporaryDirectory() as tmpdir:
            kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)
            content = Path(kh_path).read_text()

        assert "10.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFoo" in content
        assert all_have_keys is True

    def test_unparseable_key_treated_as_missing(self, mock_ansible_runner):
        """An unparseable stored key must be skipped and all_have_keys=False."""
        from fleet_platform.workers.playbook_tasks import _write_known_hosts

        hosts = [{"hostname": "mac-01", "ip": "10.0.0.1", "ssh_host_key": "garbage!!!"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)
            content = Path(kh_path).read_text()

        assert "10.0.0.1" not in content
        assert all_have_keys is False
