"""TDD tests for ARC performance fixes: #747 (async Redis), #751 (cached Fernet), #745 (non-blocking Celery)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import modules so patch.object resolves correctly.
import fleet_platform.api.routes.ingest as _ingest_mod
import fleet_platform.services.platform_settings_svc as _svc_mod


def _make_redis_mock(count: int = 1) -> tuple:
    """Return (mock_redis, mock_pipe) for the async pipeline pattern.

    redis.asyncio.Redis.pipeline() is a *synchronous* method that returns a Pipeline
    whose .execute() is the only awaitable.  Use MagicMock for the client/pipe and
    AsyncMock only for execute().
    """
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[count, True])
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    return mock_redis, mock_pipe


# ---------------------------------------------------------------------------
# #747 — _check_ingest_rate_limit must use async Redis (no sync_redis import)
# ---------------------------------------------------------------------------


def test_ingest_module_does_not_import_sync_redis():
    """#747: ingest.py must NOT hold a 'sync_redis' reference on the module."""
    assert not hasattr(_ingest_mod, "sync_redis"), (
        "ingest module still holds a 'sync_redis' reference; remove the sync import"
    )


@pytest.mark.asyncio
async def test_check_ingest_rate_limit_is_async():
    """#747: _check_ingest_rate_limit must be a coroutine function."""
    import asyncio

    from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

    assert asyncio.iscoroutinefunction(_check_ingest_rate_limit), "_check_ingest_rate_limit must be async def"


@pytest.mark.asyncio
async def test_check_ingest_rate_limit_uses_get_redis():
    """#747: _check_ingest_rate_limit must call get_redis (shared async client), not a per-request connection."""
    mock_redis, _ = _make_redis_mock(1)
    mock_get_redis = AsyncMock(return_value=mock_redis)

    with patch.object(_ingest_mod, "get_redis", mock_get_redis):
        result = await _ingest_mod._check_ingest_rate_limit("node-747")

    mock_get_redis.assert_awaited_once()
    assert result is True


@pytest.mark.asyncio
async def test_check_ingest_rate_limit_denied_over_limit():
    """#747: returns False when counter exceeds _INGEST_RATE_LIMIT."""
    from fleet_platform.api.routes.ingest import _INGEST_RATE_LIMIT

    mock_redis, _ = _make_redis_mock(_INGEST_RATE_LIMIT + 1)

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        result = await _ingest_mod._check_ingest_rate_limit("node-over")

    assert result is False


@pytest.mark.asyncio
async def test_check_ingest_rate_limit_fail_closed_on_redis_error():
    """#747: Redis error → HTTP 503 (fail-closed), not silent allow-through."""
    from fastapi import HTTPException

    with patch.object(_ingest_mod, "get_redis", AsyncMock(side_effect=Exception("redis down"))):
        with pytest.raises(HTTPException) as exc_info:
            await _ingest_mod._check_ingest_rate_limit("node-err")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_check_ingest_rate_limit_uses_pipeline_atomically():
    """#747: INCR and EXPIRE must be issued together via pipeline."""
    from fleet_platform.api.routes.ingest import _INGEST_RATE_WINDOW

    mock_redis, mock_pipe = _make_redis_mock(1)

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        await _ingest_mod._check_ingest_rate_limit("node-pipeline")

    mock_redis.pipeline.assert_called_once()
    mock_pipe.incr.assert_called_once_with("ingest_rl:node-pipeline")
    mock_pipe.expire.assert_called_once_with("ingest_rl:node-pipeline", _INGEST_RATE_WINDOW)
    mock_pipe.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# #751 — Fernet instance must be cached, not rebuilt every call
# ---------------------------------------------------------------------------


def test_fernet_instance_is_cached_across_calls():
    """#751: _fernet() must return the same Fernet instance on repeated calls (same key)."""
    _svc_mod._fernet_cache = None
    try:
        f1 = _svc_mod._fernet()
        f2 = _svc_mod._fernet()
        assert f1 is f2, "_fernet() must return a cached singleton, not a new instance each call"
    finally:
        _svc_mod._fernet_cache = None


def test_fernet_cache_invalidates_on_key_change(monkeypatch):
    """#751: cache must be invalidated when _fernet_key() output changes."""
    from cryptography.fernet import Fernet

    import fleet_platform.core.config as cfg

    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    _svc_mod._fernet_cache = None
    try:
        monkeypatch.setattr(cfg.settings, "fernet_secret_key", key_a)
        f1 = _svc_mod._fernet()

        monkeypatch.setattr(cfg.settings, "fernet_secret_key", key_b)
        f2 = _svc_mod._fernet()

        assert f1 is not f2, "Cache must be invalidated when the Fernet key changes"
    finally:
        _svc_mod._fernet_cache = None


def test_fernet_cache_does_not_store_new_key_on_same_key(monkeypatch):
    """#751: Same key → same cached instance returned, no re-construction."""
    from cryptography.fernet import Fernet

    import fleet_platform.core.config as cfg

    key = Fernet.generate_key().decode()
    _svc_mod._fernet_cache = None
    try:
        monkeypatch.setattr(cfg.settings, "fernet_secret_key", key)
        f1 = _svc_mod._fernet()
        f2 = _svc_mod._fernet()
        f3 = _svc_mod._fernet()
        assert f1 is f2 is f3
    finally:
        _svc_mod._fernet_cache = None


def test_fernet_cached_encrypt_decrypt_roundtrip():
    """#751: cached _fernet() instance encrypts/decrypts correctly."""
    _svc_mod._fernet_cache = None
    try:
        plaintext = "cached-fernet-roundtrip-test"
        ciphertext = _svc_mod.encrypt_secret(plaintext)
        assert _svc_mod.decrypt_secret(ciphertext) == plaintext
    finally:
        _svc_mod._fernet_cache = None


def test_fernet_key_validation_preserved(monkeypatch):
    """#751: _fernet_key() validation/fallback behavior must be unchanged after caching."""
    import fleet_platform.core.config as cfg

    monkeypatch.setattr(cfg.settings, "environment", "production")
    monkeypatch.setattr(cfg.settings, "fernet_secret_key", None)

    _svc_mod._fernet_cache = None
    try:
        with pytest.raises(RuntimeError, match="FERNET_KEY"):
            _svc_mod._fernet_key()
    finally:
        _svc_mod._fernet_cache = None
