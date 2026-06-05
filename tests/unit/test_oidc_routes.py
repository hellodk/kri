# tests/unit/test_oidc_routes.py
"""Unit tests for OIDC route security fixes: one-time exchange code endpoint."""

import json
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_oidc_exchange_returns_tokens_for_valid_code():
    """GET /exchange with a valid code returns the stored tokens."""
    from fleet_platform.api.routes.oidc import oidc_exchange

    tokens = {"access_token": "acc.tok.en", "refresh_token": "ref.tok.en"}
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value=json.dumps(tokens))

    result = await oidc_exchange(exchange_code="valid-code-abc", redis=mock_redis)

    mock_redis.getdel.assert_called_once_with("oidc:exchange:valid-code-abc")
    assert result["access_token"] == "acc.tok.en"
    assert result["refresh_token"] == "ref.tok.en"


@pytest.mark.asyncio
async def test_oidc_exchange_raises_400_for_missing_code():
    """GET /exchange with an unknown or expired code raises 400."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.oidc import oidc_exchange

    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value=None)  # key not found / expired

    with pytest.raises(HTTPException) as exc_info:
        await oidc_exchange(exchange_code="expired-or-unknown", redis=mock_redis)

    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.detail.lower() or "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_oidc_exchange_code_is_consumed_on_first_use():
    """Exchange code is deleted from Redis on retrieval (one-time use via getdel)."""
    from fleet_platform.api.routes.oidc import oidc_exchange

    tokens = {"access_token": "a", "refresh_token": "r"}
    call_count = 0

    async def getdel_once(key):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return json.dumps(tokens)
        return None  # consumed

    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(side_effect=getdel_once)

    # First call succeeds
    result = await oidc_exchange(exchange_code="one-time", redis=mock_redis)
    assert result["access_token"] == "a"

    # Second call raises 400 (code consumed)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await oidc_exchange(exchange_code="one-time", redis=mock_redis)
    assert exc_info.value.status_code == 400
