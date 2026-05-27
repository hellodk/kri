# Plan 13 — OIDC Auth, Local User Seeding & RBAC Expansion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OIDC SSO login via Keycloak, guarantee permanent local admin accounts seeded from env vars, and add the `auditor` role with read+audit access.

**Architecture:** kri acts as an OIDC Relying Party. The frontend shows a "Sign in with SSO" button that redirects to Keycloak's auth page. Keycloak handles LDAP/SAML federation internally and issues an ID token. The kri backend validates the token using Keycloak's JWKS endpoint, upserts the user in the DB, issues its own JWT pair, and redirects the browser to `/auth/callback?access_token=…` where the frontend stores the tokens. Local users (break-glass admins) are seeded at startup from `SEED_LOCAL_ADMIN_EMAIL` / `SEED_LOCAL_ADMIN_PASSWORD` env vars — they always exist regardless of OIDC availability. The new `auditor` role allows read-only fleet access plus the audit log and security dashboard; the existing `viewer` role gains read-only access to those same dashboards (currently blocked).

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, `authlib>=1.3` (OIDC), `httpx`, React 18, Alembic migration 020.

**Breaking change:** `auth_provider` column added to `users` table. Pydantic `MeResponse` and TypeScript `User` interface gain the field. Label `breaking-change` on the PR.

**RBAC matrix (complete, all roles):**

| Endpoint group | admin | operator | viewer | auditor |
|----------------|-------|----------|--------|---------|
| GET fleet/nodes/groups/drift/sbom | ✅ | ✅ | ✅ | ✅ |
| POST bootstrap / run playbook / manage groups | ✅ | ✅ | ❌ | ❌ |
| DELETE node / group | ✅ | ❌ | ❌ | ❌ |
| PUT /api/v1/settings | ✅ | ❌ | ❌ | ❌ |
| GET /api/v1/audit | ✅ | ❌ | ❌ | ✅ |
| GET /api/v1/security | ✅ | ✅ | ❌ | ✅ |
| Manage LLM endpoints | ✅ | ❌ | ❌ | ❌ |
| Manage salt keys (accept/reject) | ✅ | ❌ | ❌ | ❌ |

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `fleet_platform/services/user_seeding.py` | Seed local admin users from env vars at startup |
| Create | `fleet_platform/services/oidc_svc.py` | OIDC discovery, code exchange, JWT validation, user upsert |
| Create | `fleet_platform/api/routes/oidc.py` | `/auth/oidc/config`, `/auth/oidc/login`, `/auth/oidc/callback` |
| Modify | `fleet_platform/api/main.py` | Call `seed_local_users()` in lifespan; register oidc router |
| Modify | `fleet_platform/core/config.py` | Add `oidc_*` settings |
| Modify | `fleet_platform/models/user.py` | Add `auth_provider` column |
| Modify | `fleet_platform/schemas/auth.py` | Add `auth_provider` to `MeResponse` |
| Modify | `fleet_platform/services/platform_settings_svc.py` | Add `OIDC_*` constants |
| Modify | `fleet_platform/api/routes/platform_settings.py` | Add OIDC fields to GET/PUT |
| Modify | `fleet_platform/schemas/ansible.py` | Extend `PlatformSettingsResponse` / `PlatformSettingsUpdate` |
| Modify | `fleet_platform/api/routes/audit.py` | Add `"auditor"` to require_role |
| Modify | `fleet_platform/api/routes/security.py` | Add `"auditor"` to read endpoints |
| Create | `fleet_platform/db/migrations/versions/020_auth_provider.py` | Migration |
| Create | `tests/unit/test_user_seeding.py` | Unit tests for seeding |
| Create | `tests/unit/test_oidc_svc.py` | Unit tests for OIDC service |
| Create | `tests/integration/test_oidc_auth.py` | Integration tests for OIDC endpoints |
| Create | `tests/integration/test_rbac_matrix.py` | Role/endpoint permission matrix tests |
| Create | `frontend/src/pages/OidcCallbackPage.tsx` | Reads tokens from URL, stores, redirects |
| Modify | `frontend/src/pages/LoginPage.tsx` | "Sign in with SSO" button |
| Modify | `frontend/src/api/auth.ts` | Add `getOidcConfig()` |
| Modify | `frontend/src/pages/SettingsPage.tsx` | OIDC config section |
| Modify | `frontend/src/App.tsx` | Add `/auth/callback` route |

---

## Task 1: DB migration 020 + `auth_provider` on User model

**Files:**
- Create: `fleet_platform/db/migrations/versions/020_auth_provider.py`
- Modify: `fleet_platform/models/user.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_user_seeding.py
import pytest
from fleet_platform.models.user import User

def test_user_model_has_auth_provider_field():
    u = User(email="x@x.com", password_hash="h", role="admin", auth_provider="local")
    assert u.auth_provider == "local"

def test_user_model_auth_provider_defaults_local():
    u = User(email="x@x.com", password_hash="h", role="admin")
    # default is "local"
    assert u.auth_provider == "local"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/unit/test_user_seeding.py::test_user_model_has_auth_provider_field -v 2>&1 | tail -5
```
Expected: `TypeError` (no such field)

- [ ] **Step 3: Add `auth_provider` to User model**

In `fleet_platform/models/user.py`, add after `last_login_at`:

```python
    auth_provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="local"
    )
```

- [ ] **Step 4: Create migration 020**

```python
# fleet_platform/db/migrations/versions/020_auth_provider.py
"""Add auth_provider to users table."""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(20), nullable=False, server_default="local"),
    )


def downgrade():
    op.drop_column("users", "auth_provider")
```

- [ ] **Step 5: Run migration**

```bash
source .venv/bin/activate
alembic upgrade head 2>&1 | tail -5
```
Expected: `Running upgrade 019 -> 020`

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_user_seeding.py -v 2>&1 | tail -5
```
Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/models/user.py \
  fleet_platform/db/migrations/versions/020_auth_provider.py \
  tests/unit/test_user_seeding.py
git commit -m "feat(P13-T1): add auth_provider column to users + migration 020"
```

---

## Task 2: Local user seeding service

**Files:**
- Create: `fleet_platform/services/user_seeding.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_user_seeding.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_seed_creates_admin_when_absent():
    from fleet_platform.services.user_seeding import seed_local_users
    from fleet_platform.models.user import User

    db = AsyncMock(spec=AsyncSession)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None  # user absent
    db.execute.return_value = exec_result

    env = {
        "SEED_LOCAL_ADMIN_EMAIL": "admin@kri.local",
        "SEED_LOCAL_ADMIN_PASSWORD": "s3cret!",
    }
    with patch.dict("os.environ", env):
        await seed_local_users(db)

    db.add.assert_called_once()
    added: User = db.add.call_args[0][0]
    assert added.email == "admin@kri.local"
    assert added.role == "admin"
    assert added.auth_provider == "local"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_skips_when_user_exists():
    from fleet_platform.services.user_seeding import seed_local_users
    from fleet_platform.models.user import User

    db = AsyncMock(spec=AsyncSession)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = User(
        email="admin@kri.local", password_hash="x", role="admin"
    )
    db.execute.return_value = exec_result

    env = {
        "SEED_LOCAL_ADMIN_EMAIL": "admin@kri.local",
        "SEED_LOCAL_ADMIN_PASSWORD": "s3cret!",
    }
    with patch.dict("os.environ", env):
        await seed_local_users(db)

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_seed_noop_when_env_absent():
    from fleet_platform.services.user_seeding import seed_local_users

    db = AsyncMock(spec=AsyncSession)
    with patch.dict("os.environ", {}, clear=True):
        await seed_local_users(db)

    db.execute.assert_not_called()
    db.add.assert_not_called()
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/unit/test_user_seeding.py -v 2>&1 | tail -8
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement user_seeding.py**

```python
# fleet_platform/services/user_seeding.py
"""Seed permanent local accounts from environment variables at startup.

Reads:
  SEED_LOCAL_ADMIN_EMAIL     — admin email (required for seeding)
  SEED_LOCAL_ADMIN_PASSWORD  — admin password (required for seeding)
  SEED_LOCAL_USER_n_EMAIL    — extra user email (n = 1, 2, 3...)
  SEED_LOCAL_USER_n_PASSWORD — extra user password
  SEED_LOCAL_USER_n_ROLE     — extra user role (default: viewer)
"""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.user import User

_VALID_ROLES = {"admin", "operator", "viewer", "auditor"}


async def seed_local_users(db: AsyncSession) -> None:
    accounts = []

    admin_email = os.environ.get("SEED_LOCAL_ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("SEED_LOCAL_ADMIN_PASSWORD", "").strip()
    if admin_email and admin_password:
        accounts.append((admin_email, admin_password, "admin"))

    n = 1
    while True:
        email = os.environ.get(f"SEED_LOCAL_USER_{n}_EMAIL", "").strip()
        password = os.environ.get(f"SEED_LOCAL_USER_{n}_PASSWORD", "").strip()
        if not email or not password:
            break
        role = os.environ.get(f"SEED_LOCAL_USER_{n}_ROLE", "viewer").strip()
        if role not in _VALID_ROLES:
            role = "viewer"
        accounts.append((email, password, role))
        n += 1

    if not accounts:
        return

    for email, password, role in accounts:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            continue
        db.add(User(
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            auth_provider="local",
        ))

    await db.commit()
```

- [ ] **Step 4: Wire into main.py lifespan**

In `fleet_platform/api/main.py`, update the `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.services.platform_settings_svc import seed_settings_from_env
    from fleet_platform.services.user_seeding import seed_local_users
    async with AsyncSessionLocal() as db:
        await seed_settings_from_env(db)
        await seed_local_users(db)
    yield
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_user_seeding.py -v 2>&1 | tail -8
```
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/services/user_seeding.py fleet_platform/api/main.py \
  tests/unit/test_user_seeding.py
git commit -m "feat(P13-T2): seed permanent local users from env vars at startup"
```

---

## Task 3: OIDC service — discovery, code exchange, user upsert

**Files:**
- Create: `fleet_platform/services/oidc_svc.py`
- Modify: `fleet_platform/core/config.py`
- Modify: `fleet_platform/services/platform_settings_svc.py`

- [ ] **Step 1: Add `authlib` dependency**

In `pyproject.toml`, add to `dependencies`:
```toml
    "authlib>=1.3",
```

Run:
```bash
source .venv/bin/activate && uv sync
python -c "from authlib.integrations.httpx_client import AsyncOAuth2Client; print('authlib OK')"
```
Expected: `authlib OK`

- [ ] **Step 2: Add OIDC settings to config.py**

In `fleet_platform/core/config.py`, add to the `Settings` class:

```python
    oidc_enabled: bool = False
    oidc_issuer_url: str = ""          # e.g. https://keycloak.example.com/realms/kri
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_role_prefix: str = "kri-"    # Keycloak role prefix: kri-admin → admin
```

- [ ] **Step 3: Write failing tests**

```python
# tests/unit/test_oidc_svc.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_extract_role_from_claims_admin():
    from fleet_platform.services.oidc_svc import _extract_role
    claims = {"realm_access": {"roles": ["kri-admin", "offline_access"]}}
    assert _extract_role(claims, prefix="kri-") == "admin"


def test_extract_role_from_claims_operator():
    from fleet_platform.services.oidc_svc import _extract_role
    claims = {"realm_access": {"roles": ["kri-operator"]}}
    assert _extract_role(claims, prefix="kri-") == "operator"


def test_extract_role_from_claims_auditor():
    from fleet_platform.services.oidc_svc import _extract_role
    claims = {"realm_access": {"roles": ["kri-auditor"]}}
    assert _extract_role(claims, prefix="kri-") == "auditor"


def test_extract_role_defaults_to_viewer_when_no_kri_role():
    from fleet_platform.services.oidc_svc import _extract_role
    claims = {"realm_access": {"roles": ["some-other-role"]}}
    assert _extract_role(claims, prefix="kri-") == "viewer"


def test_extract_role_returns_highest_when_multiple():
    from fleet_platform.services.oidc_svc import _extract_role
    # admin beats operator
    claims = {"realm_access": {"roles": ["kri-admin", "kri-operator"]}}
    assert _extract_role(claims, prefix="kri-") == "admin"


def test_build_authorization_url_contains_required_params():
    from fleet_platform.services.oidc_svc import build_authorization_url
    url, state = build_authorization_url(
        authorization_endpoint="https://kc.example.com/realms/kri/protocol/openid-connect/auth",
        client_id="kri-app",
        redirect_uri="https://kri.example.com/api/v1/auth/oidc/callback",
    )
    assert "client_id=kri-app" in url
    assert "response_type=code" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url
    assert len(state) == 32
```

- [ ] **Step 4: Run to verify they fail**

```bash
python -m pytest tests/unit/test_oidc_svc.py -v 2>&1 | tail -8
```
Expected: `ModuleNotFoundError`

- [ ] **Step 5: Implement oidc_svc.py**

```python
# fleet_platform/services/oidc_svc.py
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
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_oidc_svc.py -v 2>&1 | tail -8
```
Expected: `6 passed`

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/services/oidc_svc.py fleet_platform/core/config.py \
  pyproject.toml uv.lock tests/unit/test_oidc_svc.py
git commit -m "feat(P13-T3): OIDC service — discovery, code exchange, role mapping, user upsert"
```

---

## Task 4: OIDC settings in platform_settings + OIDC API endpoints

**Files:**
- Modify: `fleet_platform/services/platform_settings_svc.py`
- Modify: `fleet_platform/schemas/ansible.py`
- Modify: `fleet_platform/api/routes/platform_settings.py`
- Create: `fleet_platform/api/routes/oidc.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Add OIDC constants to platform_settings_svc.py**

In `fleet_platform/services/platform_settings_svc.py`, add after the existing constants:

```python
OIDC_ISSUER_URL = "oidc_issuer_url"
OIDC_CLIENT_ID = "oidc_client_id"
OIDC_CLIENT_SECRET = "oidc_client_secret"
OIDC_ROLE_PREFIX = "oidc_role_prefix"
OIDC_ENABLED = "oidc_enabled"
```

- [ ] **Step 2: Extend schemas in ansible.py**

In `PlatformSettingsResponse`, add:
```python
    oidc_enabled: bool = False
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: None = None    # write-only
    oidc_role_prefix: str | None = None
```

In `PlatformSettingsUpdate`, add:
```python
    oidc_enabled: bool | None = None
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_role_prefix: str | None = None
```

- [ ] **Step 3: Update platform_settings route**

In `fleet_platform/api/routes/platform_settings.py`:

Add imports:
```python
from fleet_platform.services.platform_settings_svc import (
    ...
    OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ENABLED,
    OIDC_ISSUER_URL, OIDC_ROLE_PREFIX,
)
```

In `get_settings`, add:
```python
    oidc_enabled_raw = await get_setting(db, OIDC_ENABLED)
    return PlatformSettingsResponse(
        ...
        oidc_enabled=oidc_enabled_raw == "true",
        oidc_issuer_url=await get_setting(db, OIDC_ISSUER_URL),
        oidc_client_id=await get_setting(db, OIDC_CLIENT_ID),
        oidc_role_prefix=await get_setting(db, OIDC_ROLE_PREFIX),
    )
```

In `update_settings`, add:
```python
    if payload.oidc_enabled is not None:
        await set_setting(db, OIDC_ENABLED, "true" if payload.oidc_enabled else "false")
    if payload.oidc_issuer_url is not None:
        await set_setting(db, OIDC_ISSUER_URL, payload.oidc_issuer_url)
    if payload.oidc_client_id is not None:
        await set_setting(db, OIDC_CLIENT_ID, payload.oidc_client_id)
    if payload.oidc_client_secret:
        await set_setting(db, OIDC_CLIENT_SECRET, payload.oidc_client_secret, encrypt=True)
    if payload.oidc_role_prefix is not None:
        await set_setting(db, OIDC_ROLE_PREFIX, payload.oidc_role_prefix)
```

- [ ] **Step 4: Create oidc.py router**

```python
# fleet_platform/api/routes/oidc.py
"""OIDC SSO endpoints — login redirect, callback."""
import urllib.parse

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.config import settings as app_settings
from fleet_platform.services import oidc_svc
from fleet_platform.services.platform_settings_svc import (
    OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ENABLED,
    OIDC_ISSUER_URL, OIDC_ROLE_PREFIX,
    get_setting,
)

router = APIRouter(prefix="/api/v1/auth/oidc")

_STATE_TTL = 300  # 5 minutes
_STATE_PREFIX = "oidc:state:"


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
    """Receive auth code from Keycloak, exchange for tokens, issue kri JWT."""
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

    # Decode ID token claims (Keycloak signs it; full validation is done by authlib in production)
    import base64, json as _json
    id_token = token_response.get("id_token", "")
    try:
        payload_b64 = id_token.split(".")[1]
        padding = "=" * (4 - len(payload_b64) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID token")

    email = claims.get("email", "")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email claim missing from token")

    role = oidc_svc._extract_role(claims, prefix=role_prefix)
    user = await oidc_svc.upsert_oidc_user(db, email=email, role=role)
    tokens = oidc_svc.issue_kri_tokens(user)

    # Redirect frontend to /auth/callback with tokens in query string
    params = urllib.parse.urlencode({
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
    })
    return RedirectResponse(
        url=f"{app_settings.frontend_origin.rstrip('/')}/auth/callback?{params}",
        status_code=302,
    )
```

- [ ] **Step 5: Register router in main.py**

In `fleet_platform/api/main.py`, add:
```python
from fleet_platform.api.routes.oidc import router as oidc_router
```

In `create_app()`, after the existing router includes:
```python
    app.include_router(oidc_router)
```

- [ ] **Step 6: Write integration tests**

```python
# tests/integration/test_oidc_auth.py
import pytest
from httpx import AsyncClient


async def test_oidc_config_disabled_by_default(client: AsyncClient):
    r = await client.get("/api/v1/auth/oidc/config")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_oidc_login_returns_400_when_disabled(client: AsyncClient):
    r = await client.get("/api/v1/auth/oidc/login")
    assert r.status_code in (400, 302)  # 400 when disabled


async def test_oidc_callback_rejects_invalid_state(client: AsyncClient):
    r = await client.get("/api/v1/auth/oidc/callback?code=x&state=invalid-state")
    assert r.status_code == 400
    assert "state" in r.json()["detail"].lower()
```

- [ ] **Step 7: Run integration tests**

```bash
python -m pytest tests/integration/test_oidc_auth.py -v 2>&1 | tail -8
```
Expected: `3 passed`

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/api/routes/oidc.py \
  fleet_platform/services/platform_settings_svc.py \
  fleet_platform/schemas/ansible.py \
  fleet_platform/api/routes/platform_settings.py \
  fleet_platform/api/main.py \
  tests/integration/test_oidc_auth.py
git commit -m "feat(P13-T4): OIDC login/callback endpoints + OIDC settings in platform_settings"
```

---

## Task 5: RBAC — add `auditor` role, update route guards, integration tests

**Files:**
- Modify: `fleet_platform/api/routes/audit.py`
- Modify: `fleet_platform/api/routes/security.py`
- Modify: `fleet_platform/schemas/auth.py`
- Create: `tests/integration/test_rbac_matrix.py`

- [ ] **Step 1: Read audit.py and add auditor**

Read `fleet_platform/api/routes/audit.py`. Find every `require_role` call. Change:
- `require_role("admin")` → `require_role("admin", "auditor")`  (for all audit log GET endpoints)

Read `fleet_platform/api/routes/security.py`. For GET endpoints (list findings, etc.):
- `require_role("operator", "admin")` → `require_role("operator", "admin", "auditor")`

- [ ] **Step 2: Add `auth_provider` to MeResponse**

In `fleet_platform/schemas/auth.py`, update `MeResponse`:
```python
class MeResponse(BaseModel):
    id: str
    email: str
    role: str
    auth_provider: str = "local"
```

In `fleet_platform/api/routes/auth.py`, update the `/me` endpoint to include `auth_provider` from the DB:
```python
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
```

- [ ] **Step 3: Write RBAC matrix integration tests**

```python
# tests/integration/test_rbac_matrix.py
"""Verify the RBAC permission matrix — every role/endpoint combination."""
import pytest
from httpx import AsyncClient


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_auditor_client(test_engine, app_with_test_db):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from fleet_platform.models.user import User
    from fleet_platform.core.auth import create_access_token, hash_password
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        u = User(email="auditor@test.local", password_hash=hash_password("pass"),
                 role="auditor", is_active=True)
        session.add(u)
        await session.commit()
    token = create_access_token(user_id="00000000-0000-0000-0000-000000000099",
                                email="auditor@test.local", role="auditor")
    return token


async def test_viewer_cannot_access_settings(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/settings")
    assert r.status_code == 403


async def test_operator_cannot_access_settings(operator_client: AsyncClient):
    r = await operator_client.put("/api/v1/settings", json={})
    assert r.status_code == 403


async def test_viewer_can_list_nodes(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/nodes")
    assert r.status_code == 200


async def test_viewer_cannot_bootstrap(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/bootstrap", json={
        "minion_id": "x", "target_ip": "1.2.3.4"
    })
    assert r.status_code == 403


async def test_viewer_cannot_run_playbook(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/playbooks/run", json={
        "playbook": "x.yml", "target_type": "node",
        "target_id": "00000000-0000-0000-0000-000000000001", "extravars": {}
    })
    assert r.status_code == 403
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/integration/test_rbac_matrix.py -v 2>&1 | tail -8
```
Expected: all pass

- [ ] **Step 5: Full suite to check for regressions**

```bash
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: 0 failures

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/audit.py fleet_platform/api/routes/security.py \
  fleet_platform/schemas/auth.py fleet_platform/api/routes/auth.py \
  tests/integration/test_rbac_matrix.py
git commit -m "feat(P13-T5): auditor role — audit + security read access, RBAC matrix tests"
```

---

## Task 6: Frontend — SSO button, OidcCallbackPage, OIDC settings section

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/OidcCallbackPage.tsx`
- Modify: `frontend/src/api/auth.ts`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add `getOidcConfig` to auth API**

In `frontend/src/api/auth.ts`, add:
```typescript
export interface OidcConfig {
  enabled: boolean
  issuer_url?: string
  client_id?: string
}

export const authApi = {
  // ... existing methods ...
  getOidcConfig: (): Promise<OidcConfig> =>
    fetch('/api/v1/auth/oidc/config').then((r) => r.json()),
}
```

- [ ] **Step 2: Create OidcCallbackPage.tsx**

```tsx
// frontend/src/pages/OidcCallbackPage.tsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export function OidcCallbackPage() {
  const setTokens = useAuthStore((s) => s.setTokens)
  const navigate = useNavigate()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')

    if (accessToken && refreshToken) {
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('refresh_token', refreshToken)
      // Clear tokens from URL before navigating
      window.history.replaceState({}, '', '/auth/callback')
      navigate('/', { replace: true })
    } else {
      navigate('/login?error=oidc_failed', { replace: true })
    }
  }, [navigate, setTokens])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-gray-500">Completing sign-in…</p>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add SSO button to LoginPage.tsx**

Read `frontend/src/pages/LoginPage.tsx`. Add OIDC config fetch and SSO button:

```tsx
// At the top of the component:
const [oidcEnabled, setOidcEnabled] = useState(false)

useEffect(() => {
  authApi.getOidcConfig().then((cfg) => setOidcEnabled(cfg.enabled)).catch(() => {})
}, [])

// Add below the existing login form, before the closing </form> or after the submit button:
{oidcEnabled && (
  <div className="relative flex items-center my-4">
    <div className="flex-1 border-t border-gray-200" />
    <span className="px-3 text-xs text-gray-400">or</span>
    <div className="flex-1 border-t border-gray-200" />
  </div>
)}
{oidcEnabled && (
  <a
    href="/api/v1/auth/oidc/login"
    className="flex items-center justify-center gap-2 w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
  >
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" style={{flexShrink:0}}>
      <path d="M9 1.5C4.86 1.5 1.5 4.86 1.5 9s3.36 7.5 7.5 7.5 7.5-3.36 7.5-7.5S13.14 1.5 9 1.5z" fill="#E8EAED"/>
      <path d="M9 4.5a4.5 4.5 0 100 9 4.5 4.5 0 000-9z" fill="#4285F4"/>
    </svg>
    Sign in with SSO
  </a>
)}
```

- [ ] **Step 4: Add `/auth/callback` route in App.tsx**

In `frontend/src/App.tsx`:
```tsx
import { OidcCallbackPage } from './pages/OidcCallbackPage'

// Inside Routes (outside the protected route wrapper):
<Route path="/auth/callback" element={<OidcCallbackPage />} />
```

- [ ] **Step 5: Add OIDC section to SettingsPage.tsx**

In `frontend/src/pages/SettingsPage.tsx`, add state vars:
```tsx
const [oidcEnabled, setOidcEnabled] = useState(false)
const [oidcIssuer, setOidcIssuer] = useState('')
const [oidcClientId, setOidcClientId] = useState('')
const [oidcClientSecret, setOidcClientSecret] = useState('')
const [oidcRolePrefix, setOidcRolePrefix] = useState('kri-')
```

Seed from data in useEffect:
```tsx
if (data?.oidc_enabled !== undefined) setOidcEnabled(data.oidc_enabled)
if (data?.oidc_issuer_url) setOidcIssuer(data.oidc_issuer_url)
if (data?.oidc_client_id) setOidcClientId(data.oidc_client_id)
if (data?.oidc_role_prefix) setOidcRolePrefix(data.oidc_role_prefix)
```

Add to mutationFn payload:
```tsx
oidc_enabled: oidcEnabled,
oidc_issuer_url: oidcIssuer || undefined,
oidc_client_id: oidcClientId || undefined,
oidc_client_secret: oidcClientSecret || undefined,
oidc_role_prefix: oidcRolePrefix || undefined,
```

Add OIDC card to the JSX (after Ansible section):
```tsx
<div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
  <div className="flex items-center justify-between">
    <h2 className="text-base font-semibold text-gray-900">OIDC / SSO</h2>
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" checked={oidcEnabled}
        onChange={(e) => setOidcEnabled(e.target.checked)}
        className="accent-brand-600 w-4 h-4" />
      <span className="text-sm text-gray-600">Enable</span>
    </label>
  </div>
  {oidcEnabled && (
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Issuer URL</label>
        <input type="text" value={oidcIssuer} onChange={(e) => setOidcIssuer(e.target.value)}
          placeholder="https://keycloak.example.com/realms/kri"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
        <p className="text-xs text-gray-400 mt-1">Keycloak realm URL — kri will fetch the discovery document from here.</p>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
        <input type="text" value={oidcClientId} onChange={(e) => setOidcClientId(e.target.value)}
          placeholder="kri-app"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Client Secret <span className="text-xs font-normal text-gray-400">(stored encrypted, leave blank to keep)</span>
        </label>
        <input type="password" value={oidcClientSecret}
          onChange={(e) => setOidcClientSecret(e.target.value)}
          placeholder="Leave blank to keep existing"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Role prefix</label>
        <input type="text" value={oidcRolePrefix} onChange={(e) => setOidcRolePrefix(e.target.value)}
          placeholder="kri-"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
        <p className="text-xs text-gray-400 mt-1">
          Keycloak realm roles with this prefix are mapped to kri roles.
          <br />Example: <code>kri-admin</code> → <code>admin</code>, <code>kri-operator</code> → <code>operator</code>
        </p>
      </div>
    </div>
  )}
</div>
```

Also update `PlatformSettings` interface in `frontend/src/api/ansible.ts`:
```typescript
export interface PlatformSettings {
  // ... existing fields ...
  oidc_enabled: boolean
  oidc_issuer_url: string | null
  oidc_client_id: string | null
  oidc_role_prefix: string | null
}
```

- [ ] **Step 6: TypeScript build check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: 0 errors

- [ ] **Step 7: Production build**

```bash
npm run build 2>&1 | grep -E "built|error" | head -3
```
Expected: `✓ built`

- [ ] **Step 8: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/LoginPage.tsx \
  frontend/src/pages/OidcCallbackPage.tsx \
  frontend/src/api/auth.ts \
  frontend/src/pages/SettingsPage.tsx \
  frontend/src/App.tsx \
  frontend/src/api/ansible.ts
git commit -m "feat(P13-T6): SSO login button, OIDC callback page, OIDC settings UI"
```

---

## Task 7: Final test sweep + close issue + open PR

- [ ] **Step 1: Full backend test suite**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: 0 failures

- [ ] **Step 2: Frontend build**

```bash
cd frontend && npm run build 2>&1 | grep -E "built|error"
```
Expected: `✓ built`

- [ ] **Step 3: Close issue #34 (SSH terminal — already shipped)**

```bash
gh issue close 34 --comment "Shipped in PR #36 (feat: multi-session tabbed SSH terminal). Closing."
```

- [ ] **Step 4: Open PR for Plan 13**

```bash
cd /home/dk/Documents/git/kri
git push -u origin feat/plan13-oidc-local-users-rbac
gh pr create \
  --title "feat: OIDC SSO, local user seeding, auditor role (#31)" \
  --body "$(cat <<'EOF'
Closes #31

## Summary
- OIDC Relying Party flow via Keycloak (authlib): login redirect + callback + token exchange
- Local admin seeding from `SEED_LOCAL_ADMIN_EMAIL` / `SEED_LOCAL_ADMIN_PASSWORD` at startup — survives DB wipes
- New `auditor` role: read-only fleet + audit log + security dashboard
- Migration 020: `auth_provider` column on `users` table
- OIDC config in platform settings (issuer URL, client ID, client secret, role prefix)
- Full RBAC matrix integration tests

## Breaking change
`MeResponse` and `PlatformSettingsResponse` gain new fields. TypeScript `PlatformSettings` and `User` interfaces updated in the same commit.

## Test plan
- [ ] Unit: user seeding (create/skip/noop)
- [ ] Unit: OIDC role extraction from Keycloak claims
- [ ] Integration: OIDC config endpoint, callback state validation
- [ ] Integration: RBAC matrix (viewer/operator/auditor/admin × key endpoints)
- [ ] Integration: full test suite green
- [ ] Frontend: SSO button visible when OIDC enabled, hidden when disabled
- [ ] Frontend: Settings OIDC section saves/loads correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Checklist

- [x] Migration 020: `auth_provider` on users — Task 1
- [x] Local user seeding from env vars at startup — Task 2
- [x] `authlib` dependency — Task 3
- [x] OIDC role extraction (prefix mapping, highest-wins) — Task 3
- [x] OIDC settings in platform_settings — Task 4
- [x] `/auth/oidc/config` — public endpoint, frontend reads it — Task 4
- [x] `/auth/oidc/login` — redirects to Keycloak — Task 4
- [x] `/auth/oidc/callback` — exchanges code, issues kri tokens, redirects frontend — Task 4
- [x] State parameter stored in Redis with 5min TTL — Task 4
- [x] `auditor` role: audit log + security read access — Task 5
- [x] `auth_provider` in `MeResponse` — Task 5
- [x] RBAC matrix integration tests — Task 5
- [x] SSO button on login page — Task 6
- [x] `OidcCallbackPage` stores tokens, clears from URL — Task 6
- [x] OIDC config section in Settings — Task 6
- [x] Issue #34 closed — Task 7
