"""Shared SSH reachability probe.

One probe implementation, two callers:
- the 15-minute :func:`check_ssh_connectivity` sweep (passive baseline), and
- the on-demand ``POST /api/v1/nodes/{id}/ssh-test`` endpoint (instant refresh).

Why this is richer than online/offline (#356 follow-up): a single TCP check
cannot tell *"host down"* from *"port open but the key/password was rejected"*.
The first means fix the machine; the second means fix the credentials. So the
probe returns one of four states:

- ``ok``           — TCP :22 open **and** authentication succeeded.
- ``auth_failed``  — TCP :22 open but the key/password was rejected.
- ``unreachable``  — TCP :22 closed, filtered, or timed out.
- ``unknown``      — no IP on record, or no stored credential to attempt auth
                     (we report TCP reachability but cannot verify login).

Auth is verified with ``asyncssh`` (already a dependency for WebSSH). Using the
library's in-memory key import instead of a temp key file deliberately sidesteps
the ``chmod 0600`` temp-file footgun that made the old subprocess probe return
false negatives for key auth (#743).
"""

from __future__ import annotations

import asyncio
import logging
import socket

logger = logging.getLogger(__name__)

# Probe states (kept short — persisted verbatim to Node.ssh_state and sent to the UI).
SSH_OK = "ok"
SSH_AUTH_FAILED = "auth_failed"
SSH_UNREACHABLE = "unreachable"
SSH_UNKNOWN = "unknown"

_TCP_TIMEOUT = 5  # seconds — TCP connect and SSH handshake budget


def _tcp_open(ip: str, timeout: int) -> bool:
    """Return True if a TCP connection to ``ip:22`` succeeds within ``timeout``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((ip, 22)) == 0
    except OSError:
        return False
    finally:
        sock.close()


async def _probe_ssh_auth(
    ip: str,
    user: str,
    auth_mode: str,
    key: str,
    password: str,
    timeout: int,
) -> dict:
    """Attempt a real SSH handshake and classify the outcome.

    Assumes TCP :22 is already known to be open (caller did the cheap pre-check),
    so a connection failure here is treated as ``unreachable`` and a credential
    rejection as ``auth_failed``.
    """
    import asyncssh

    connect_kwargs: dict = {
        "host": ip,
        "port": 22,
        "username": user,
        "known_hosts": None,  # reachability probe — host-key TOFU is out of scope
        "connect_timeout": timeout,
        # Never fall back to the controller's ssh-agent or on-disk default keys;
        # we want to test exactly the credential resolved for this node.
        "agent_path": None,
    }
    if auth_mode == "key" and key:
        try:
            client_key = asyncssh.import_private_key(key)
        except Exception as exc:  # noqa: BLE001 — bad/passphrased key is a credential problem
            return {"state": SSH_AUTH_FAILED, "detail": f"invalid private key: {str(exc)[:120]}"}
        connect_kwargs["client_keys"] = [client_key]
    else:
        connect_kwargs["password"] = password
        connect_kwargs["client_keys"] = []  # password-only: don't attempt key auth

    try:
        conn = await asyncssh.connect(**connect_kwargs)
        conn.close()
        try:
            await conn.wait_closed()
        except Exception:  # noqa: BLE001 — close is best-effort
            pass
        return {"state": SSH_OK, "detail": "authenticated"}
    except asyncssh.PermissionDenied as exc:
        return {"state": SSH_AUTH_FAILED, "detail": f"authentication rejected: {str(exc)[:120]}"}
    except (asyncssh.Error, OSError, asyncio.TimeoutError) as exc:  # noqa: UP041
        return {"state": SSH_UNREACHABLE, "detail": f"connection failed: {str(exc)[:120]}"}


def probe_node_ssh(node, creds: dict, *, timeout: int = _TCP_TIMEOUT) -> dict:
    """Probe one node's SSH reachability. Never raises.

    ``node`` needs only ``.ip_address`` / ``.minion_id``; ``creds`` is the dict
    from :func:`resolve_node_credentials` (keys: ``ssh_user``, ``ssh_password``,
    ``ssh_key``, ``auth_mode``). Returns ``{"state": ..., "detail": ...}``.

    Safe to call from sync (Celery worker) and from async code via
    ``asyncio.to_thread`` — the auth handshake runs in its own event loop.
    """
    ip = getattr(node, "ip_address", None)
    if not ip:
        return {"state": SSH_UNKNOWN, "detail": "no IP address on record"}
    ip = str(ip)

    auth_mode = creds.get("auth_mode", "password")
    key = creds.get("ssh_key") or ""
    password = creds.get("ssh_password") or ""
    user = creds.get("ssh_user") or "admin"
    has_secret = bool(key) if auth_mode == "key" else bool(password)

    try:
        # Cheap TCP classification first: distinguishes "host down" fast and
        # cheaply, before paying for an SSH handshake.
        if not _tcp_open(ip, timeout):
            return {"state": SSH_UNREACHABLE, "detail": "TCP port 22 closed or timed out"}

        if not has_secret:
            # Port is open but there's no credential to verify a login with.
            return {"state": SSH_UNKNOWN, "detail": "port 22 open; auth not verified (no stored credential)"}

        return asyncio.run(_probe_ssh_auth(ip, user, auth_mode, key, password, timeout))
    except Exception as exc:  # noqa: BLE001 — a probe must never crash its caller
        logger.debug("ssh probe error node=%s: %s", getattr(node, "minion_id", "?"), exc)
        return {"state": SSH_UNREACHABLE, "detail": f"probe error: {str(exc)[:120]}"}


def ssh_state_to_reachable(state: str) -> int:
    """Map a probe state to the legacy 0/1 reachability signal (Redis/Prometheus).

    Only an authenticated ``ok`` counts as reachable-and-usable; everything else
    (auth_failed / unreachable / unknown) is 0 for the ``kri_node_ssh_reachable``
    gauge, preserving its original "can we actually use SSH here" meaning.
    """
    return 1 if state == SSH_OK else 0
