"""Behavioural tests for jti enforcement in get_current_user (#505).

These tests call get_current_user directly (with mocked Redis) and assert
that tokens without a jti claim or with a revoked jti are rejected with 401.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

_WORKTREE = Path(__file__).resolve().parents[2]
_SECRET = "test-secret-minimum-32-characters-long"


def _make_token(payload: dict) -> str:
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def _override_settings():
    """Patch fleet_platform.core.config.settings to use the test secret."""
    from unittest.mock import MagicMock

    s = MagicMock()
    s.jwt_secret = _SECRET
    s.jwt_algorithm = "HS256"
    return s


@pytest.fixture(autouse=True)
def patch_settings():
    with patch("fleet_platform.core.auth.settings", _override_settings()):
        yield


@pytest.mark.asyncio
async def test_token_without_jti_raises_401():
    """A token that has no 'jti' claim must be rejected with 401."""
    from fleet_platform.core.auth import get_current_user

    token_no_jti = _make_token({"sub": "user1", "email": "u@x.com", "role": "viewer", "type": "access"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_no_jti)
    fake_redis = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds, redis=fake_redis)

    assert exc_info.value.status_code == 401
    assert "jti" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_token_with_revoked_jti_raises_401():
    """A token whose jti is in the Redis revocation set must be rejected with 401."""
    from fleet_platform.core.auth import get_current_user

    token = _make_token(
        {"sub": "user1", "email": "u@x.com", "role": "viewer", "type": "access", "jti": "revoked-jti-abc"}
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # Simulate Redis returning 1 (key exists) — token is revoked
    fake_redis = AsyncMock()
    fake_redis.exists = AsyncMock(return_value=1)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds, redis=fake_redis)

    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_valid_token_with_jti_succeeds():
    """A token with a valid jti that is NOT revoked returns the claims dict."""
    from fleet_platform.core.auth import get_current_user

    token = _make_token(
        {"sub": "user1", "email": "u@x.com", "role": "viewer", "type": "access", "jti": "valid-jti-xyz"}
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # Simulate Redis returning 0 (key does not exist) — token is valid
    fake_redis = AsyncMock()
    fake_redis.exists = AsyncMock(return_value=0)

    claims = await get_current_user(credentials=creds, redis=fake_redis)

    assert claims["jti"] == "valid-jti-xyz"
    assert claims["email"] == "u@x.com"
