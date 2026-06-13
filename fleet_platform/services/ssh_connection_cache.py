"""SSH connection cache for WebSSH session reuse.

Caches asyncssh connections keyed by (host, port, username) with a 5-minute
idle TTL. Bounded to MAX_CACHED_CONNECTIONS to prevent leaks.

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


async def get_connection(
    host: str,
    port: int,
    username: str,
    connect_kwargs: dict,
) -> "asyncssh.SSHClientConnection":
    """Return a cached connection or create a new one."""
    import asyncssh

    key = (host, port, username)

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
