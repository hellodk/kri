"""OIDC Relying Party service — discovery, authorization URL, code exchange, user upsert."""
import secrets
import urllib.parse
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import create_access_token, create_refresh_token, hash_password
from fleet_platform.models.user import User

_ROLE_PRIORITY = {"admin": 4, "operator": 3, "auditor": 2, "viewer": 1}
_VALID_ROLES = set(_ROLE_PRIORITY)


def _extract_role(claims: dict, prefix: str) -> str:
    roles = claims.get("realm_access", {}).get("roles", [])
    kri_roles = [r[len(prefix):] for r in roles if r.startswith(prefix)]
    valid = [r for r in kri_roles if r in _VALID_ROLES]
    if not valid:
        return "viewer"
    return max(valid, key=lambda r: _ROLE_PRIORITY[r])


def build_authorization_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
) -> tuple[str, str]:
    state = secrets.token_hex(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
    }
    url = authorization_endpoint + "?" + urllib.parse.urlencode(params)
    return url, state


async def discover(issuer_url: str) -> dict:
    discovery_url = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        return resp.json()


async def exchange_code(
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def upsert_oidc_user(
    db: AsyncSession,
    email: str,
    role: str,
) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_hex(32)),  # unusable password
            role=role,
            is_active=True,
            auth_provider="oidc",
        )
        db.add(user)
    else:
        # Refresh role from IdP on every login
        user.role = role
        user.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


def issue_kri_tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role,
        ),
        "refresh_token": create_refresh_token(user_id=str(user.id)),
    }
