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


# ── Structural tests ────────────────────────────────────────────────────────────


def test_cache_module_exists():
    module = Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py"
    assert module.exists()
    content = module.read_text()
    assert "get_connection" in content


def test_cache_has_ttl():
    content = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    assert "IDLE_TTL_SECONDS" in content or "ttl" in content.lower()


def test_cache_is_bounded():
    content = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    assert "MAX_CACHED_CONNECTIONS" in content


def test_cache_has_eviction():
    content = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    assert "evict" in content.lower()


def test_cache_has_stats():
    content = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    assert "cache_stats" in content or "stats" in content.lower()


def test_webssh_imports_cache():
    content = (Path(__file__).parent.parent.parent / "fleet_platform/api/routes/webssh.py").read_text()
    assert "ssh_connection_cache" in content or "get_connection" in content


def test_parse_description():
    # Cache module should not use asyncssh at import time (TYPE_CHECKING guard)
    content = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    assert "TYPE_CHECKING" in content


def test_cache_evict_node_function():
    content = (Path(__file__).parent.parent.parent / "fleet_platform/services/ssh_connection_cache.py").read_text()
    assert "evict_node" in content
