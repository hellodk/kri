"""Tests for #166: SSH connection cache."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── Behavioural tests (mock asyncssh.connect) ─────────────────────────────────


def _make_conn(closed: bool = False) -> MagicMock:
    conn = MagicMock()
    conn.is_closed.return_value = closed
    conn.close = MagicMock()
    return conn


def test_cached_conn_is_alive():
    from fleet_platform.services.ssh_connection_cache import _CachedConn

    conn = _make_conn(closed=False)
    c = _CachedConn(conn=conn)
    assert c.is_alive() is True


def test_cached_conn_not_alive_when_closed():
    from fleet_platform.services.ssh_connection_cache import _CachedConn

    conn = _make_conn(closed=True)
    c = _CachedConn(conn=conn)
    assert c.is_alive() is False


def test_cached_conn_idle_expired():
    from fleet_platform.services.ssh_connection_cache import _CachedConn

    conn = _make_conn()
    c = _CachedConn(conn=conn, last_used=time.monotonic() - 400)
    assert c.is_idle_expired() is True


def test_cached_conn_not_idle_expired():
    from fleet_platform.services.ssh_connection_cache import _CachedConn

    conn = _make_conn()
    c = _CachedConn(conn=conn)
    assert c.is_idle_expired() is False


def test_cache_stats_returns_dict():
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    stats = ssh_connection_cache.cache_stats()
    assert "total" in stats
    assert "max" in stats
    assert "ttl_seconds" in stats
    assert stats["total"] == 0


def test_cache_stats_counts_entries():
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    ssh_connection_cache._cache[("h1", 22, "u")] = ssh_connection_cache._CachedConn(conn=_make_conn())
    ssh_connection_cache._cache[("h2", 22, "u")] = ssh_connection_cache._CachedConn(conn=_make_conn())
    stats = ssh_connection_cache.cache_stats()
    assert stats["total"] == 2
    ssh_connection_cache._cache.clear()


def test_evict_node_removes_matching():
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    conn1 = _make_conn()
    conn2 = _make_conn()
    ssh_connection_cache._cache[("target", 22, "user")] = ssh_connection_cache._CachedConn(conn=conn1)
    ssh_connection_cache._cache[("other", 22, "user")] = ssh_connection_cache._CachedConn(conn=conn2)

    count = asyncio.run(ssh_connection_cache.evict_node("target"))
    assert count == 1
    assert ("target", 22, "user") not in ssh_connection_cache._cache
    assert ("other", 22, "user") in ssh_connection_cache._cache
    ssh_connection_cache._cache.clear()


def test_get_connection_creates_and_caches():
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    fake_conn = _make_conn()

    async def run():
        with patch("asyncssh.connect", new=AsyncMock(return_value=fake_conn)):
            conn = await ssh_connection_cache.get_connection("h", 22, "u", {"host": "h"})
        return conn

    result = asyncio.run(run())
    assert result is fake_conn
    expected_key = ("h", 22, "u", ssh_connection_cache._credential_fingerprint({"host": "h"}))
    assert expected_key in ssh_connection_cache._cache
    ssh_connection_cache._cache.clear()


def test_get_connection_reuses_cached():
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    fake_conn = _make_conn()
    key = ("h", 22, "u", ssh_connection_cache._credential_fingerprint({}))
    ssh_connection_cache._cache[key] = ssh_connection_cache._CachedConn(conn=fake_conn)

    async def run():
        with patch("asyncssh.connect", new=AsyncMock(side_effect=AssertionError("should not call connect"))):
            return await ssh_connection_cache.get_connection("h", 22, "u", {})

    result = asyncio.run(run())
    assert result is fake_conn
    assert ssh_connection_cache._cache[key].use_count == 1
    ssh_connection_cache._cache.clear()


def test_get_connection_evicts_dead_before_reuse():
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    dead_conn = _make_conn(closed=True)
    new_conn = _make_conn()
    ssh_connection_cache._cache[("h", 22, "u")] = ssh_connection_cache._CachedConn(conn=dead_conn)

    async def run():
        with patch("asyncssh.connect", new=AsyncMock(return_value=new_conn)):
            return await ssh_connection_cache.get_connection("h", 22, "u", {"host": "h"})

    result = asyncio.run(run())
    assert result is new_conn
    ssh_connection_cache._cache.clear()


# ── Structural tests (hardened: hasattr / module-namespace checks) ─────────────


def test_cache_module_exists():
    from fleet_platform.services import ssh_connection_cache

    assert hasattr(ssh_connection_cache, "get_connection"), "ssh_connection_cache must expose a get_connection function"


def test_cache_has_ttl():
    from fleet_platform.services import ssh_connection_cache

    assert hasattr(ssh_connection_cache, "IDLE_TTL_SECONDS") or hasattr(ssh_connection_cache, "TTL_SECONDS"), (
        "ssh_connection_cache must define an IDLE_TTL_SECONDS constant"
    )


def test_cache_is_bounded():
    from fleet_platform.services import ssh_connection_cache

    assert hasattr(ssh_connection_cache, "MAX_CACHED_CONNECTIONS"), (
        "ssh_connection_cache must define a MAX_CACHED_CONNECTIONS bound"
    )


def test_cache_has_eviction():
    from fleet_platform.services import ssh_connection_cache

    assert hasattr(ssh_connection_cache, "evict_node"), "ssh_connection_cache must expose an evict_node function"


def test_cache_has_stats():
    from fleet_platform.services import ssh_connection_cache

    assert hasattr(ssh_connection_cache, "cache_stats"), "ssh_connection_cache must expose a cache_stats function"


def test_webssh_imports_cache():
    from fleet_platform.api.routes import webssh

    assert hasattr(webssh, "get_connection") or hasattr(webssh, "ssh_connection_cache"), (
        "webssh must import get_connection (or ssh_connection_cache) to use the SSH connection pool"
    )


def test_parse_description():
    # Cache module should not use asyncssh at import time — verified via AST TYPE_CHECKING guard.
    import ast

    src = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    tree = ast.parse(src)
    has_type_checking_guard = any(
        isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        for node in ast.walk(tree)
    )
    assert has_type_checking_guard, (
        "ssh_connection_cache must guard asyncssh import under TYPE_CHECKING to avoid import-time side effects"
    )


def test_cache_evict_node_function():
    from fleet_platform.services import ssh_connection_cache

    assert hasattr(ssh_connection_cache, "evict_node") and callable(ssh_connection_cache.evict_node), (
        "ssh_connection_cache must expose a callable evict_node function"
    )
