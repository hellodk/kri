import logging
import uuid as _uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fleet_platform.api.deps import get_redis
from fleet_platform.core.config import settings

logger = logging.getLogger(__name__)

_REVOKE_PREFIX = "rt:revoked:"


def _new_jti() -> str:
    return str(_uuid_mod.uuid4())


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


# ── Password hashing ──────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ── Token creation ────────────────────────────────────────────────────


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "jti": _new_jti(),
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": _new_jti(),
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ── Token decoding ────────────────────────────────────────────────────


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("Token has expired")
    except jwt.PyJWTError:
        raise TokenInvalidError("Token is invalid")


async def revoke_token(redis: aioredis.Redis, jti: str, ttl_seconds: int) -> None:
    await redis.setex(f"{_REVOKE_PREFIX}{jti}", ttl_seconds, "1")


async def is_token_revoked(redis: aioredis.Redis, jti: str) -> bool:
    return await redis.exists(f"{_REVOKE_PREFIX}{jti}") == 1


# ── FastAPI dependencies ──────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    redis: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any]:
    if not credentials:
        raise _unauthorized("Missing Authorization header")
    try:
        claims = decode_token(credentials.credentials)
    except TokenExpiredError:
        raise _unauthorized("Token has expired")
    except TokenInvalidError:
        raise _unauthorized("Invalid token")
    if claims.get("type") != "access":
        raise _unauthorized("Refresh tokens cannot access this endpoint")
    jti = claims.get("jti", "")
    if jti:
        try:
            if await is_token_revoked(redis, jti):
                raise _unauthorized("Token has been revoked")
        except aioredis.RedisError:
            logger.error("Redis unavailable during token revocation check — denying request")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service temporarily unavailable"
            )
    return claims


def require_role(*roles: str):
    """FastAPI dependency factory. Usage: Depends(require_role('admin', 'operator'))"""

    async def dependency(claims: dict = Depends(get_current_user)) -> dict:
        if claims.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{claims.get('role')}' cannot access this endpoint",
            )
        return claims

    return dependency
