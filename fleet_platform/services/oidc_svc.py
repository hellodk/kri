"""OIDC Relying Party service — discovery, authorization URL, code exchange, user upsert."""

import base64
import json
import secrets
import urllib.parse
from datetime import UTC, datetime
from typing import cast

import httpx
import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import create_access_token, create_refresh_token, hash_password
from fleet_platform.models.user import User

_ROLE_PRIORITY = {"admin": 4, "operator": 3, "auditor": 2, "viewer": 1}
_VALID_ROLES = set(_ROLE_PRIORITY)


def _extract_role(claims: dict, prefix: str) -> str:
    roles = claims.get("realm_access", {}).get("roles", [])
    kri_roles = [r[len(prefix) :] for r in roles if r.startswith(prefix)]
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


async def verify_id_token(id_token: str, discovery: dict, client_id: str) -> dict:
    """Verify ID token signature using the IdP's JWKS and return the validated claims."""
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        raise ValueError("JWKS URI not in discovery document")

    # Fetch JWKS from the IdP
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        jwks = resp.json()

    # Decode the JWT header to find the key ID (kid)
    header_b64 = id_token.split(".")[0]
    padding = "=" * (4 - len(header_b64) % 4)
    header = json.loads(base64.urlsafe_b64decode(header_b64 + padding))
    kid = header.get("kid")

    # Find the matching public key in the JWKS
    matching_key = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            matching_key = key
            break
    if matching_key is None and jwks.get("keys"):
        matching_key = jwks["keys"][0]  # fallback: use first key if no kid match

    if not matching_key:
        raise ValueError("No matching key found in JWKS")

    # Reconstruct the RSA public key and verify the token signature
    public_key = cast(RSAPublicKey, pyjwt.algorithms.RSAAlgorithm.from_jwk(matching_key))
    claims = pyjwt.decode(
        id_token,
        public_key,
        algorithms=["RS256"],
        audience=client_id,
    )
    return claims


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
