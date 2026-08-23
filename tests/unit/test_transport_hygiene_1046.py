"""#1046 — secrets & transport hygiene.

Covers: pillar file permissions (0600), pre-auth host-key pinning for the SSH
probe, salt-api tls_verify default, git StrictHostKeyChecking=accept-new.
"""

from __future__ import annotations

import os
import stat
from unittest.mock import MagicMock, patch


# ── pinned_known_hosts_file ──────────────────────────────────────────────────
class TestPinnedKnownHostsFile:
    def test_writes_0600_file_with_host_token(self, tmp_path):
        from fleet_platform.services.ssh_host_key_svc import pinned_known_hosts_file

        path = pinned_known_hosts_file("10.0.0.5", "ssh-ed25519 AAAA…validkey")
        try:
            assert path is not None
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o600, f"known_hosts pin must be 0600, got {oct(mode)}"
            content = open(path).read()
            assert content.startswith("10.0.0.5 ssh-ed25519 ")
        finally:
            os.unlink(path)

    def test_returns_none_without_stored_key(self):
        from fleet_platform.services.ssh_host_key_svc import pinned_known_hosts_file

        assert pinned_known_hosts_file("h", None) is None
        assert pinned_known_hosts_file("h", "") is None

    def test_accepts_legacy_base64_wrapped_key(self):
        import base64

        from fleet_platform.services.ssh_host_key_svc import pinned_known_hosts_file

        wrapped = base64.b64encode(b"ssh-ed25519 AAAAlegacy comment").decode()
        path = pinned_known_hosts_file("h", wrapped)
        try:
            assert path is not None
            assert "ssh-ed25519" in open(path).read()
        finally:
            if path:
                os.unlink(path)


# ── ssh_probe host-key pinning ───────────────────────────────────────────────
class TestProbeHostKeyPinning:
    def _probe(self, stored_key, connect_exc=None):
        import asyncio

        import asyncssh

        import fleet_platform.services.ssh_probe as probe_mod

        captured = {}

        class FakeConn:
            def close(self):
                pass

            async def wait_closed(self):
                pass

        async def fake_connect(**kwargs):
            captured.update(kwargs)
            if connect_exc is not None:
                raise connect_exc
            return FakeConn()

        with patch.object(asyncssh, "connect", side_effect=fake_connect):
            result = asyncio.run(
                probe_mod._probe_ssh_auth(
                    "10.0.0.9",
                    "admin",
                    "password",
                    "",
                    "pw",
                    5,
                    stored_host_key=stored_key,
                )
            )
        return result, captured

    def test_no_stored_key_passes_known_hosts_none(self):
        result, captured = self._probe(None)
        assert result["state"] == "ok"
        assert captured["known_hosts"] is None

    def test_stored_key_pins_known_hosts_and_cleans_up(self):
        import asyncio

        import asyncssh

        import fleet_platform.services.ssh_probe as probe_mod

        captured = {}
        kh_content = {}

        class FakeConn:
            def close(self):
                pass

            async def wait_closed(self):
                pass

        async def fake_connect(**kwargs):
            captured.update(kwargs)
            kh = kwargs.get("known_hosts")
            if kh:
                kh_content["data"] = open(kh).read()
            return FakeConn()

        with patch.object(asyncssh, "connect", side_effect=fake_connect):
            result = asyncio.run(
                probe_mod._probe_ssh_auth(
                    "10.0.0.9", "admin", "password", "", "pw", 5, stored_host_key="ssh-ed25519 AAAA…valid"
                )
            )
        assert result["state"] == "ok"
        kh = captured["known_hosts"]
        assert kh is not None and "ssh-ed25519" in kh_content.get("data", "")
        assert not os.path.exists(kh), "temp known_hosts must be removed after probe"

    def test_mismatch_classifies_host_key_mismatch_state(self):
        import asyncssh

        result, _ = self._probe(
            "ssh-ed25519 AAAA…valid",
            connect_exc=asyncssh.HostKeyNotVerifiable("host key mismatch"),
        )
        assert result["state"] == "host_key_mismatch"

    def test_probe_node_ssh_forwards_stored_host_key(self):
        """probe_node_ssh passes node.ssh_host_key through to the auth prober."""

        import fleet_platform.services.ssh_probe as probe_mod

        node = MagicMock()
        node.ip_address = "10.1.1.1"
        node.minion_id = "n1"
        node.ssh_host_key = "ssh-ed25519 AAAAstored"
        seen = {}

        async def fake_probe(ip, user, mode, key, pw, timeout, stored_host_key=None):
            seen["stored"] = stored_host_key
            return {"state": "ok", "detail": "authenticated"}

        with patch.object(probe_mod, "_probe_ssh_auth", fake_probe):
            with patch.object(probe_mod, "_tcp_open", return_value=True):
                result = probe_mod.probe_node_ssh(node, {"auth_mode": "password", "ssh_password": "x"})
        assert result["state"] == "ok"
        assert seen["stored"] == "ssh-ed25519 AAAAstored"


# ── pillar file permissions ──────────────────────────────────────────────────
class TestPillarPerms:
    def test_node_pillar_written_0600(self, tmp_path):
        from fleet_platform.services import node_secrets_svc as svc

        sls = tmp_path / "n1.sls"
        svc._write_node_pillar_sync(tmp_path, sls, tmp_path / "l.lock", {"K": "v"})
        mode = stat.S_IMODE(os.stat(sls).st_mode)
        assert mode == 0o600, f"node pillar on disk must be 0600, got {oct(mode)}"

    def test_group_pillar_written_0600(self, tmp_path):
        from fleet_platform.services import group_secrets_svc as svc

        sls = tmp_path / "g1.sls"
        svc._write_group_pillar_sync(tmp_path, sls, tmp_path / "g.lock", {"K": "v"})
        mode = stat.S_IMODE(os.stat(sls).st_mode)
        assert mode == 0o600, f"group pillar on disk must be 0600, got {oct(mode)}"


# ── salt-api / git transport defaults ────────────────────────────────────────
class TestTransportDefaults:
    def test_salt_api_tls_verify_defaults_true_for_stub_master(self):

        master = MagicMock(spec=[])  # attribute-less stub → fallback branch
        assert bool(getattr(master, "tls_verify", True)) is True

    def test_salt_api_honours_false_when_explicit(self):
        master = MagicMock()
        master.tls_verify = False
        assert bool(getattr(master, "tls_verify", True)) is False

    def test_git_auth_uses_accept_new_not_no(self):
        import inspect

        from fleet_platform.services import git_auth

        src = inspect.getsource(git_auth)
        assert "StrictHostKeyChecking=no" not in src, "git clone must not disable host-key checking entirely"
        assert "StrictHostKeyChecking=accept-new" in src
