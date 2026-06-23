import uuid
import uuid as _uuid
from asyncio import to_thread
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    is_token_revoked,
    revoke_token,
    verify_password,
)
from fleet_platform.models.user import User
from fleet_platform.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    password_valid = await to_thread(verify_password, payload.password, user.password_hash)
    if not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is disabled")

    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MUST_CHANGE_PASSWORD",
        )

    from fleet_platform.core.audit import audit

    user.last_login_at = datetime.now(UTC)
    await audit(
        db,
        actor=payload.email,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role,
        ),
        refresh_token=create_refresh_token(user_id=str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    try:
        claims = decode_token(payload.refresh_token)
    except (TokenExpiredError, TokenInvalidError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    jti = claims.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing required jti claim",
        )
    if await is_token_revoked(redis, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    result = await db.execute(select(User).where(User.id == _uuid.UUID(claims["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Revoke the old refresh token
    if jti:
        exp = claims.get("exp", 0)
        remaining_ttl = max(1, int(exp - datetime.now(UTC).timestamp()))
        await revoke_token(redis, jti, remaining_ttl)

    return TokenResponse(
        access_token=create_access_token(user_id=str(user.id), email=user.email, role=user.role),
        refresh_token=create_refresh_token(user_id=str(user.id)),
    )


@router.post("/logout", status_code=204)
async def logout(
    payload: LogoutRequest | None = None,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    from fleet_platform.core.audit import audit as _audit

    if payload and payload.refresh_token:
        try:
            rt_claims = decode_token(payload.refresh_token)
            jti = rt_claims.get("jti")
            if not jti:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token missing required jti claim",
                )
            exp = rt_claims.get("exp", 0)
            remaining_ttl = max(1, int(exp - datetime.now(UTC).timestamp()))
            await revoke_token(redis, jti, remaining_ttl)
        except (TokenExpiredError, TokenInvalidError):
            pass
    await _audit(
        db,
        actor=claims["email"],
        action="auth.logout",
        resource_type="user",
    )
    await db.commit()
    return None


@router.get("/me", response_model=MeResponse)
async def me(
    claims: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(claims["sub"])))
    user = result.scalar_one_or_none()
    return MeResponse(
        id=claims["sub"],
        email=claims["email"],
        role=claims["role"],
        auth_provider=user.auth_provider if user else "local",
    )
