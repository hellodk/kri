from datetime import timedelta

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
    token = create_access_token(
        user_id="user-123", email="a@b.com", role="viewer",
        expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(TokenExpiredError):
        decode_token(token)


def test_invalid_token_raises():
    with pytest.raises(TokenInvalidError):
        decode_token("not.a.valid.token")
