from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from fleet_platform.core.auth import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    token = create_access_token(user_id="user-123", email="a@b.com", role="viewer")
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["email"] == "a@b.com"
    assert claims["role"] == "viewer"
    assert claims["type"] == "access"


def test_create_and_decode_refresh_token():
    token = create_refresh_token(user_id="user-123")
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["type"] == "refresh"


def test_expired_token_raises():
    token = create_access_token(user_id="user-123", email="a@b.com", role="viewer", expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenExpiredError):
        decode_token(token)


def test_invalid_token_raises():
    with pytest.raises(TokenInvalidError):
        decode_token("not.a.valid.token")


@pytest.mark.asyncio
async def test_get_current_user_raises_if_jti_revoked():
    """get_current_user must check JTI against Redis revocation list and raise 401 if revoked."""
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from fleet_platform.core.auth import get_current_user

    token = create_access_token(user_id="u1", email="x@x.com", role="viewer")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    mock_redis = AsyncMock()

    # Mock is_token_revoked to return True (token is revoked)
    with patch("fleet_platform.core.auth.is_token_revoked", new=AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds, redis=mock_redis)

    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_current_user_passes_when_jti_not_revoked():
    """get_current_user returns claims normally when JTI is not revoked."""
    from fastapi.security import HTTPAuthorizationCredentials

    from fleet_platform.core.auth import get_current_user

    token = create_access_token(user_id="u2", email="y@y.com", role="admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    mock_redis = AsyncMock()

    with patch("fleet_platform.core.auth.is_token_revoked", new=AsyncMock(return_value=False)):
        claims = await get_current_user(credentials=creds, redis=mock_redis)

    assert claims["sub"] == "u2"
    assert claims["type"] == "access"
