"""Unit tests for issue #743 — SSH probe temp key file permissions."""

import os
import stat
import tempfile
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

_RealNamedTemporaryFile = tempfile.NamedTemporaryFile


def _make_node(minion_id: str, ip: str = "192.168.1.10") -> MagicMock:
    node = MagicMock()
    node.minion_id = minion_id
    node.ip_address = ip
    return node


def _creds(auth_mode: str = "key", ssh_key: str = "FAKE_KEY_MATERIAL\n") -> dict:
    return {
        "ssh_user": "admin",
        "ssh_password": "secret",
        "ssh_key": ssh_key,
        "auth_mode": auth_mode,
        "credential_source": "global",
    }


class _FakeSocket:
    def settimeout(self, t):
        pass

    def connect_ex(self, addr):
        return 0

    def close(self):
        pass


@contextmanager
def _permissive_temp_file(*args, **kwargs):
    """Simulate a temp key file with world-readable perms (OpenSSH rejects this)."""
    with _RealNamedTemporaryFile(*args, **kwargs) as tmp:
        os.chmod(tmp.name, 0o644)
        yield tmp


def test_ssh_key_temp_file_has_mode_0600_before_ssh():
    """Probe must chmod the temp SSH key to 0o600 before invoking ssh -i."""
    from fleet_platform.workers.connectivity_tasks import _probe_node

    node = _make_node("mac-mini-key-perms")
    creds = _creds()

    key_modes: list[int] = []

    def capture_key_mode(*args, **kwargs):
        cmd = args[0]
        key_idx = cmd.index("-i") + 1
        key_path = cmd[key_idx]
        key_modes.append(stat.S_IMODE(os.stat(key_path).st_mode))
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        return fake_proc

    with (
        patch("fleet_platform.workers.connectivity_tasks.socket.socket", return_value=_FakeSocket()),
        patch(
            "fleet_platform.workers.connectivity_tasks.tempfile.NamedTemporaryFile",
            _permissive_temp_file,
        ),
        patch("fleet_platform.workers.connectivity_tasks.subprocess.run", side_effect=capture_key_mode),
    ):
        result = _probe_node(node, creds)

    assert result == 1
    assert key_modes == [0o600], f"expected temp key mode 0o600, got {key_modes!r}"
