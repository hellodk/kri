"""SSH connection cache for WebSSH session reuse.

Caches asyncssh connections keyed by (host, port, username, cred_fingerprint)
with a 5-minute idle TTL. Bounded to MAX_CACHED_CONNECTIONS to prevent leaks.

The credential fingerprint is a SHA-256 hex digest of the auth material
(password, client_keys, passphrase, known_hosts) so that two callers sharing
the same host/port/username but presenting DIFFERENT credentials receive
separate cache entries — preventing silent authentication bypass.

Multi-replica caveat: this cache is per-process. When the API runs with
replicas > 1, a client whose request lands on replica B cannot reuse a
connection cached on replica A. The short-term mitigation is k8s
sessionAffinity=ClientIP on the api Service (deploy/k8s/api-service.yaml);
the long-term fix is to externalise the registry to Redis so any replica
can serve any session — see the strategic-backlog issue tied to B2 in the
sprint plan.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncssh

_log = logging.getLogger(__name__)

MAX_CACHED_CONNECTIONS = 50
IDLE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class _CachedConn:
    conn: "asyncssh.SSHClientConnection"
    last_used: float = field(default_factory=time.monotonic)
    use_count: int = 0

    def is_alive(self) -> bool:
        try:
            return not self.conn.is_closed()
        except Exception:
            return False

    def is_idle_expired(self) -> bool:
        return (time.monotonic() - self.last_used) > IDLE_TTL_SECONDS


_cache: dict[tuple, _CachedConn] = {}
_lock = asyncio.Lock()

# Auth-material keys whose values are included in the credential fingerprint.
_CRED_KEYS = ("password", "client_keys", "passphrase", "known_hosts")


def _credential_fingerprint(connect_kwargs: dict) -> str:
    """Return a stable SHA-256 hex digest of the auth material in *connect_kwargs*.

    Only fields that actually carry authentication secrets are hashed
    (``password``, ``client_keys``, ``passphrase``, ``known_hosts``).
    The raw values are NEVER logged or stored — only this digest is used.

    ``client_keys`` entries may be file paths (str), raw bytes, or asyncssh
    key objects.  Each entry is normalised to bytes before hashing; non-bytes
    values fall back to their ``repr()`` so distinct objects produce distinct
    digests even when their type is opaque.
    """
    h = hashlib.sha256()
    for field_name in _CRED_KEYS:
        value = connect_kwargs.get(field_name)
        if value is None:
            continue
        h.update(field_name.encode())
        h.update(b":")
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, bytes):
                    h.update(item)
                elif isinstance(item, str):
                    h.update(item.encode())
                else:
                    h.update(repr(item).encode())
                h.update(b"\x00")
        elif isinstance(value, bytes):
            h.update(value)
        elif isinstance(value, str):
            h.update(value.encode())
        else:
            h.update(repr(value).encode())
        h.update(b"\xff")
    return h.hexdigest()


async def get_connection(
    host: str,
    port: int,
    username: str,
    connect_kwargs: dict,
) -> "asyncssh.SSHClientConnection":
    """Return a cached connection or create a new one."""
    import asyncssh

    cred_fp = _credential_fingerprint(connect_kwargs)
    key = (host, port, username, cred_fp)

    async with _lock:
        # Evict dead/expired entries
        dead_keys = [k for k, v in _cache.items() if not v.is_alive() or v.is_idle_expired()]
        for k in dead_keys:
            try:
                _cache[k].conn.close()
            except Exception:
                pass
            del _cache[k]
            _log.debug("ssh_cache: evicted %s", k)

        # Check for a live cached connection
        if key in _cache:
            cached = _cache[key]
            cached.last_used = time.monotonic()
            cached.use_count += 1
            _log.debug("ssh_cache: reusing connection to %s:%s (use_count=%d)", host, port, cached.use_count)
            return cached.conn

        # Enforce bound
        if len(_cache) >= MAX_CACHED_CONNECTIONS:
            # Evict the oldest entry
            oldest_key = min(_cache, key=lambda k: _cache[k].last_used)
            try:
                _cache[oldest_key].conn.close()
            except Exception:
                pass
            del _cache[oldest_key]
            _log.debug("ssh_cache: evicted oldest entry %s (cache full)", oldest_key)

        # Create new connection
        conn = await asyncssh.connect(**connect_kwargs)
        _cache[key] = _CachedConn(conn=conn, use_count=1)
        _log.debug("ssh_cache: new connection to %s:%s (cache_size=%d)", host, port, len(_cache))
        return conn


async def evict_node(host: str) -> int:
    """Remove all cached connections to a given host. Returns eviction count."""
    async with _lock:
        keys_to_evict = [k for k in _cache if k[0] == host]
        for k in keys_to_evict:
            try:
                _cache[k].conn.close()
            except Exception:
                pass
            del _cache[k]
        return len(keys_to_evict)


def cache_stats() -> dict:
    """Return current cache statistics (no lock — approximate only)."""
    return {
        "total": len(_cache),
        "alive": sum(1 for v in _cache.values() if v.is_alive()),
        "max": MAX_CACHED_CONNECTIONS,
        "ttl_seconds": IDLE_TTL_SECONDS,
    }
