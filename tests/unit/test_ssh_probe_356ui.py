"""Unit tests for the shared SSH probe (#356-ui).

Covers the four-state classifier in ``fleet_platform.services.ssh_probe``:
- no IP -> unknown
- TCP closed -> unreachable
- TCP open, no stored credential -> unknown (port open, auth unverifiable)
- TCP open + auth success -> ok
- TCP open + auth rejected -> auth_failed
- the asyncssh handshake exception mapping
- the legacy 0/1 reachability mapping
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from fleet_platform.services import ssh_probe
from fleet_platform.services.ssh_probe import (
    SSH_AUTH_FAILED,
    SSH_OK,
    SSH_UNKNOWN,
    SSH_UNREACHABLE,
    probe_node_ssh,
    ssh_state_to_reachable,
)


def _node(ip="192.168.1.10", minion_id="n1"):
    n = MagicMock()
    n.ip_address = ip
    n.minion_id = minion_id
    return n


def _creds(auth_mode="password", password="secret", key=""):
    return {"ssh_user": "admin", "ssh_password": password, "ssh_key": key, "auth_mode": auth_mode}


# --- probe_node_ssh classification ----------------------------------------


def test_no_ip_returns_unknown():
    node = _node(ip=None)
    assert probe_node_ssh(node, _creds())["state"] == SSH_UNKNOWN


def test_tcp_closed_returns_unreachable():
    with patch.object(ssh_probe, "_tcp_open", return_value=False):
        out = probe_node_ssh(_node(), _creds())
    assert out["state"] == SSH_UNREACHABLE


def test_tcp_open_no_secret_returns_unknown():
    """Port open but no usable credential -> unknown (can't verify auth)."""
    with patch.object(ssh_probe, "_tcp_open", return_value=True):
        out = probe_node_ssh(_node(), _creds(auth_mode="password", password=""))
    assert out["state"] == SSH_UNKNOWN


def test_tcp_open_auth_success_returns_ok():
    async def _fake_auth(*a, **k):
        return {"state": SSH_OK, "detail": "authenticated"}

    with (
        patch.object(ssh_probe, "_tcp_open", return_value=True),
        patch.object(ssh_probe, "_probe_ssh_auth", new=_fake_auth),
    ):
        out = probe_node_ssh(_node(), _creds(password="pw"))
    assert out["state"] == SSH_OK


def test_tcp_open_auth_rejected_returns_auth_failed():
    async def _fake_auth(*a, **k):
        return {"state": SSH_AUTH_FAILED, "detail": "authentication rejected"}

    with (
        patch.object(ssh_probe, "_tcp_open", return_value=True),
        patch.object(ssh_probe, "_probe_ssh_auth", new=_fake_auth),
    ):
        out = probe_node_ssh(_node(), _creds(password="pw"))
    assert out["state"] == SSH_AUTH_FAILED


def test_probe_never_raises_on_internal_error():
    with patch.object(ssh_probe, "_tcp_open", side_effect=RuntimeError("boom")):
        out = probe_node_ssh(_node(), _creds())
    assert out["state"] == SSH_UNREACHABLE


# --- _probe_ssh_auth handshake mapping ------------------------------------


def test_auth_handshake_success_maps_ok():
    conn = MagicMock()
    conn.wait_closed = AsyncMock(return_value=None)
    with patch("asyncssh.connect", new=AsyncMock(return_value=conn)):
        out = asyncio.run(ssh_probe._probe_ssh_auth("1.2.3.4", "admin", "password", "", "pw", 5))
    assert out["state"] == SSH_OK


def test_auth_handshake_permission_denied_maps_auth_failed():
    with patch("asyncssh.connect", new=AsyncMock(side_effect=asyncssh.PermissionDenied("denied"))):
        out = asyncio.run(ssh_probe._probe_ssh_auth("1.2.3.4", "admin", "password", "", "pw", 5))
    assert out["state"] == SSH_AUTH_FAILED


def test_auth_handshake_connection_error_maps_unreachable():
    with patch("asyncssh.connect", new=AsyncMock(side_effect=OSError("conn refused"))):
        out = asyncio.run(ssh_probe._probe_ssh_auth("1.2.3.4", "admin", "password", "", "pw", 5))
    assert out["state"] == SSH_UNREACHABLE


def test_auth_invalid_key_maps_auth_failed():
    """A key that fails import is a credential problem, not unreachability."""
    out = asyncio.run(ssh_probe._probe_ssh_auth("1.2.3.4", "admin", "key", "NOT-A-REAL-KEY", "", 5))
    assert out["state"] == SSH_AUTH_FAILED


# --- legacy reachable mapping ---------------------------------------------


@pytest.mark.parametrize(
    "state,expected",
    [(SSH_OK, 1), (SSH_AUTH_FAILED, 0), (SSH_UNREACHABLE, 0), (SSH_UNKNOWN, 0)],
)
def test_ssh_state_to_reachable(state, expected):
    assert ssh_state_to_reachable(state) == expected


# --- route registration ----------------------------------------------------


def test_ssh_routes_registered():
    from fleet_platform.api.routes.nodes import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes if hasattr(r, "methods")}
    assert ("/api/v1/nodes/{node_id}/ssh-test", ("POST",)) in paths
    assert ("/api/v1/nodes/ssh-refresh", ("POST",)) in paths
