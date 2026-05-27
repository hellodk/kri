"""OIDC SSO endpoints — login redirect, callback, one-time exchange."""

import json
import secrets

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.config import settings as app_settings
from fleet_platform.services import oidc_svc
from fleet_platform.services.platform_settings_svc import (
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ENABLED,
    OIDC_ISSUER_URL,
    OIDC_ROLE_PREFIX,
    get_setting,
)

router = APIRouter(prefix="/api/v1/auth/oidc")

_STATE_TTL = 300  # 5 minutes
_STATE_PREFIX = "oidc:state:"
_EXCHANGE_PREFIX = "oidc:exchange:"
_EXCHANGE_TTL = 30  # 30 seconds — one-time code


@router.get("/config")
async def oidc_config(db: AsyncSession = Depends(get_db)):
    """Return OIDC configuration for the frontend (public endpoint)."""
    enabled_raw = await get_setting(db, OIDC_ENABLED)
    enabled = enabled_raw == "true"
    if not enabled:
        return {"enabled": False}
    issuer = await get_setting(db, OIDC_ISSUER_URL) or ""
    client_id = await get_setting(db, OIDC_CLIENT_ID) or ""
    return {"enabled": True, "issuer_url": issuer, "client_id": client_id}


@router.get("/login")
async def oidc_login(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Redirect the browser to the Keycloak authorization page."""
    enabled_raw = await get_setting(db, OIDC_ENABLED)
    if enabled_raw != "true":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC not enabled")

    issuer = await get_setting(db, OIDC_ISSUER_URL) or ""
    client_id = await get_setting(db, OIDC_CLIENT_ID) or ""
    if not issuer or not client_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC not configured")

    try:
        discovery = await oidc_svc.discover(issuer)
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC discovery failed")

    redirect_uri = f"{app_settings.frontend_origin.rstrip('/')}/auth/callback"
    url, state = oidc_svc.build_authorization_url(
        authorization_endpoint=discovery["authorization_endpoint"],
        client_id=client_id,
        redirect_uri=redirect_uri,
    )
    await redis.setex(f"{_STATE_PREFIX}{state}", _STATE_TTL, "1")
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback")
async def oidc_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Receive auth code from Keycloak, exchange for tokens, issue kri JWT via one-time code."""
    key = f"{_STATE_PREFIX}{state}"
    valid = await redis.getdel(key)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired state")

    issuer = await get_setting(db, OIDC_ISSUER_URL) or ""
    client_id = await get_setting(db, OIDC_CLIENT_ID) or ""
    client_secret = await get_setting(db, OIDC_CLIENT_SECRET) or ""
    role_prefix = await get_setting(db, OIDC_ROLE_PREFIX) or "kri-"

    try:
        discovery = await oidc_svc.discover(issuer)
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC discovery failed")

    redirect_uri = f"{app_settings.frontend_origin.rstrip('/')}/auth/callback"
    try:
        token_response = await oidc_svc.exchange_code(
            token_endpoint=discovery["token_endpoint"],
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token exchange failed")

    # Verify the ID token signature using the IdP's JWKS (fix #79)
    id_token = token_response.get("id_token", "")
    try:
        claims = await oidc_svc.verify_id_token(
            id_token=id_token,
            discovery=discovery,
            client_id=client_id,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID token verification failed")

    email = claims.get("email", "")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email claim missing from token")

    role = oidc_svc._extract_role(claims, prefix=role_prefix)
    user = await oidc_svc.upsert_oidc_user(db, email=email, role=role)
    tokens = oidc_svc.issue_kri_tokens(user)

    # Store tokens behind a one-time exchange code; redirect with only the code (fix #84)
    exchange_code = secrets.token_urlsafe(32)
    await redis.setex(f"{_EXCHANGE_PREFIX}{exchange_code}", _EXCHANGE_TTL, json.dumps(tokens))
    return RedirectResponse(
        url=f"{app_settings.frontend_origin.rstrip('/')}/auth/callback?exchange_code={exchange_code}",
        status_code=302,
    )


@router.get("/exchange")
async def oidc_exchange(
    exchange_code: str,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Exchange one-time code for tokens. Code expires in 30s and is consumed on first use."""
    key = f"{_EXCHANGE_PREFIX}{exchange_code}"
    raw = await redis.getdel(key)
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired exchange code")
    return json.loads(raw)
