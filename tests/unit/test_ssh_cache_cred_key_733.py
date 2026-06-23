"""Tests for SSH connection cache credential-keying fix (issue #733).

Verifies that two callers connecting to the same host:port:username but with
DIFFERENT credentials each get their own cache entry (no auth bypass), while
identical credentials still share a single connection.

asyncssh.connect is patched per-test; the real asyncssh module is used so that
its exception classes remain intact for other tests in the suite.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_conn():
    conn = MagicMock()
    conn.is_closed.return_value = False
    conn.close.return_value = None
    return conn


# ---------------------------------------------------------------------------
# Fixtures: isolate the module-level cache between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the SSH connection cache and lock before each test."""
    from fleet_platform.services import ssh_connection_cache

    ssh_connection_cache._cache.clear()
    ssh_connection_cache._lock = asyncio.Lock()
    yield
    ssh_connection_cache._cache.clear()


# ---------------------------------------------------------------------------
# Test 1: Different passwords → two cache entries, connect called twice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_passwords_create_separate_entries():
    """Two calls with same host/port/user but different passwords must NOT share a connection."""
    from fleet_platform.services import ssh_connection_cache

    conn_a = _make_fake_conn()
    conn_b = _make_fake_conn()

    kwargs_a = {"host": "10.0.0.1", "port": 22, "username": "admin", "password": "pw_aaa"}
    kwargs_b = {"host": "10.0.0.1", "port": 22, "username": "admin", "password": "pw_bbb"}

    mock_connect = AsyncMock(side_effect=[conn_a, conn_b])
    with patch.object(asyncssh, "connect", mock_connect):
        result_a = await ssh_connection_cache.get_connection("10.0.0.1", 22, "admin", kwargs_a)
        result_b = await ssh_connection_cache.get_connection("10.0.0.1", 22, "admin", kwargs_b)

    # asyncssh.connect must have been called twice
    assert mock_connect.call_count == 2, (
        f"Expected 2 calls to asyncssh.connect but got {mock_connect.call_count}. "
        "Different passwords must not reuse each other's connection."
    )

    # The two returned connections are distinct
    assert result_a is conn_a
    assert result_b is conn_b

    # Two separate cache entries must exist
    assert len(ssh_connection_cache._cache) == 2, (
        f"Expected 2 cache entries but found {len(ssh_connection_cache._cache)}."
    )


# ---------------------------------------------------------------------------
# Test 2: Identical credentials → one cache entry, connect called once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identical_credentials_reuse_connection():
    """Two calls with identical creds must reuse the cached connection."""
    from fleet_platform.services import ssh_connection_cache

    conn = _make_fake_conn()
    kwargs = {"host": "10.0.0.1", "port": 22, "username": "admin", "password": "pw_same"}

    mock_connect = AsyncMock(return_value=conn)
    with patch.object(asyncssh, "connect", mock_connect):
        result_a = await ssh_connection_cache.get_connection("10.0.0.1", 22, "admin", kwargs)
        result_b = await ssh_connection_cache.get_connection("10.0.0.1", 22, "admin", kwargs)

    assert mock_connect.call_count == 1, (
        f"Expected 1 call to asyncssh.connect but got {mock_connect.call_count}. "
        "Identical creds should reuse the cached connection."
    )
    assert result_a is result_b
    assert len(ssh_connection_cache._cache) == 1


# ---------------------------------------------------------------------------
# Test 3: Different client_keys → two separate cache entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_client_keys_create_separate_entries():
    """Different client_keys must produce distinct cache entries."""
    from fleet_platform.services import ssh_connection_cache

    conn_a = _make_fake_conn()
    conn_b = _make_fake_conn()

    key_bytes_a = b"FAKE_KEY_MATERIAL_FOR_TESTING_ONLY_AAAA_1111"
    key_bytes_b = b"FAKE_KEY_MATERIAL_FOR_TESTING_ONLY_BBBB_2222"

    kwargs_a = {"host": "10.0.0.2", "port": 22, "username": "root", "client_keys": [key_bytes_a]}
    kwargs_b = {"host": "10.0.0.2", "port": 22, "username": "root", "client_keys": [key_bytes_b]}

    mock_connect = AsyncMock(side_effect=[conn_a, conn_b])
    with patch.object(asyncssh, "connect", mock_connect):
        result_a = await ssh_connection_cache.get_connection("10.0.0.2", 22, "root", kwargs_a)
        result_b = await ssh_connection_cache.get_connection("10.0.0.2", 22, "root", kwargs_b)

    assert mock_connect.call_count == 2, (
        f"Expected 2 calls to asyncssh.connect but got {mock_connect.call_count}. "
        "Different client_keys must not reuse each other's connection."
    )
    assert result_a is conn_a
    assert result_b is conn_b
    assert len(ssh_connection_cache._cache) == 2


# ---------------------------------------------------------------------------
# Test 4: Fingerprint does not leak raw secret
# ---------------------------------------------------------------------------


def test_credential_fingerprint_does_not_leak_secret():
    """The credential fingerprint must be a fixed-length hex digest, never the raw secret."""
    from fleet_platform.services.ssh_connection_cache import _credential_fingerprint

    password = "pw_abc99"
    fingerprint = _credential_fingerprint({"password": password, "host": "h", "port": 22, "username": "u"})

    # Must be a 64-char hex string (SHA-256)
    assert len(fingerprint) == 64, f"Expected 64-char hex digest, got {len(fingerprint)} chars: {fingerprint!r}"
    assert all(c in "0123456789abcdef" for c in fingerprint), f"Fingerprint is not lowercase hex: {fingerprint!r}"

    # Must NOT contain the raw password
    assert password not in fingerprint, "Raw password must not appear in the fingerprint!"

    # Two different passwords must produce different digests
    fp2 = _credential_fingerprint({"password": "pw_xyz88", "host": "h", "port": 22, "username": "u"})
    assert fingerprint != fp2, "Different passwords must produce different fingerprints."
