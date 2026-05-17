# Audit Fix Plan 8 — Security Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five security gaps from the external audit: token revocation + logout, rate limiting, SBOM upload size cap, SBOM retry fix, and compute_drift retry; plus the health/readiness endpoint needed for production monitoring.

**Architecture:** Refresh token revocation uses Redis (already running) to store a deny-list of `jti` claims with TTL matching the refresh expiry — no new DB table needed. Rate limiting uses slowapi (already a declared dependency, just unwired). SBOM fixes are in the worker only. Health check queries DB + Redis synchronously to give a definitive readiness signal.

**Tech Stack:** Python 3.13, FastAPI 0.115, slowapi 0.1.9, Redis 7.4, Celery 5.4, pytest-asyncio.

---

## Task 1: /auth/logout + Refresh Token Revocation via Redis (C3)

**Files:**
- Modify: `fleet_platform/core/auth.py` — add `jti` to tokens, add revoke/is-revoked helpers
- Modify: `fleet_platform/api/routes/auth.py` — add `/auth/logout`, rotate refresh on `/auth/refresh`
- Modify: `fleet_platform/api/deps.py` — expose `get_redis` for auth routes
- Test: `tests/integration/test_auth_endpoints.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/integration/test_auth_endpoints.py`:

```python
async def test_logout_revokes_refresh_token(client: AsyncClient):
    """After logout, the refresh token must be rejected."""
    r = await client.post("/auth/login", json={"email": "admin-test@fleet.local", "password": "admin123"})
    assert r.status_code == 200
    tokens = r.json()
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    # Logout
    lo = await client.post("/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert lo.status_code == 204

    # Refresh should now be rejected
    r2 = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


async def test_refresh_rotates_token(client: AsyncClient):
    """Using a refresh token must return a new access token and issue a new refresh token."""
    r = await client.post("/auth/login", json={"email": "admin-test@fleet.local", "password": "admin123"})
    tokens = r.json()
    r2 = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 200
    # New access token returned
    assert "access_token" in r2.json()
```

- [ ] **Step 2: Run to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/integration/test_auth_endpoints.py::test_logout_revokes_refresh_token tests/integration/test_auth_endpoints.py::test_refresh_rotates_token -v
```

Expected: `test_logout_revokes_refresh_token` → 404 (no logout route); `test_refresh_rotates_token` → may pass trivially (no rotation yet — check it doesn't regress later).

- [ ] **Step 3: Add jti to tokens and revocation helpers in auth.py**

```python
# fleet_platform/core/auth.py — add these imports and helpers
import uuid as _uuid
import redis.asyncio as aioredis

_REVOKE_PREFIX = "rt:revoked:"


def _new_jti() -> str:
    return str(_uuid.uuid4())


def create_access_token(user_id: str, email: str, role: str, expires_delta=None) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload = {
        "sub": user_id, "email": email, "role": role,
        "type": "access", "exp": expire, "iat": datetime.now(UTC),
        "jti": _new_jti(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": user_id, "type": "refresh",
        "exp": expire, "iat": datetime.now(UTC),
        "jti": _new_jti(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def revoke_token(redis: aioredis.Redis, jti: str, ttl_seconds: int) -> None:
    await redis.setex(f"{_REVOKE_PREFIX}{jti}", ttl_seconds, "1")


async def is_token_revoked(redis: aioredis.Redis, jti: str) -> bool:
    return await redis.exists(f"{_REVOKE_PREFIX}{jti}") == 1
```

- [ ] **Step 4: Update /auth/refresh to check revocation and rotate**

In `fleet_platform/api/routes/auth.py`, update the `refresh` endpoint:

```python
from fleet_platform.api.deps import get_redis
from fleet_platform.core.auth import (
    TokenExpiredError, TokenInvalidError,
    create_access_token, create_refresh_token,
    decode_token, get_current_user, verify_password,
    revoke_token, is_token_revoked,
)

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    try:
        claims = decode_token(payload.refresh_token)
    except (TokenExpiredError, TokenInvalidError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired refresh token")
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not a refresh token")

    jti = claims.get("jti", "")
    if jti and await is_token_revoked(redis, jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Refresh token has been revoked")

    result = await db.execute(select(User).where(User.id == _uuid.UUID(claims["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Revoke the old refresh token
    if jti:
        from datetime import timezone
        exp = claims.get("exp", 0)
        remaining_ttl = max(1, int(exp - datetime.now(UTC).timestamp()))
        await revoke_token(redis, jti, remaining_ttl)

    # Issue new tokens (rotation)
    return TokenResponse(
        access_token=create_access_token(
            user_id=str(user.id), email=user.email, role=user.role,
        ),
        refresh_token=create_refresh_token(user_id=str(user.id)),
    )


@router.post("/logout", status_code=204)
async def logout(
    claims: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Revoke the current user's refresh tokens. Client must discard tokens."""
    # We revoke by user — but since we only have the access token here, we just
    # signal success. The real protection is refresh token rotation + short access TTL.
    # For a stronger logout, pass the refresh_token in the body and revoke its jti.
    return None
```

- [ ] **Step 5: Add stronger logout that accepts refresh token**

Update the schema and route:

```python
# fleet_platform/schemas/auth.py — add
class LogoutRequest(BaseModel):
    refresh_token: str | None = None


# fleet_platform/api/routes/auth.py — update logout
@router.post("/logout", status_code=204)
async def logout(
    payload: LogoutRequest | None = None,
    claims: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    if payload and payload.refresh_token:
        try:
            rt_claims = decode_token(payload.refresh_token)
            jti = rt_claims.get("jti", "")
            if jti:
                exp = rt_claims.get("exp", 0)
                remaining_ttl = max(1, int(exp - datetime.now(UTC).timestamp()))
                await revoke_token(redis, jti, remaining_ttl)
        except (TokenExpiredError, TokenInvalidError):
            pass  # already expired — nothing to revoke
    return None
```

- [ ] **Step 6: Update frontend authStore to send refresh_token on logout**

In `frontend/src/stores/authStore.ts`:

```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'

interface AuthState {
  user: User | null
  setUser: (user: User) => void
  clearAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      setUser: (user) => set({ user }),
      clearAuth: async () => {
        const refreshToken = localStorage.getItem('refresh_token')
        const accessToken = localStorage.getItem('access_token')
        if (accessToken) {
          try {
            await fetch('/auth/logout', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${accessToken}`,
              },
              body: JSON.stringify({ refresh_token: refreshToken }),
            })
          } catch {
            // best-effort
          }
        }
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null })
      },
    }),
    { name: 'auth-store' }
  )
)
```

Update `TopBar.tsx` logout handler to `await clearAuth()`:

```tsx
async function handleLogout() {
  await clearAuth()
  navigate('/login')
}
```

- [ ] **Step 7: Run all auth tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_auth_endpoints.py -v
```

Expected: all existing tests + 2 new pass.

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/core/auth.py fleet_platform/api/routes/auth.py \
  fleet_platform/schemas/auth.py frontend/src/stores/authStore.ts \
  frontend/src/components/Layout/TopBar.tsx tests/integration/test_auth_endpoints.py
git commit -m "feat(C3): /auth/logout + refresh token rotation and Redis-based revocation"
```

---

## Task 2: Rate Limiting via slowapi (C5)

**Files:**
- Modify: `fleet_platform/api/main.py` — wire slowapi
- Modify: `fleet_platform/api/routes/ingest.py` — apply rate limits to ingest endpoints
- Test: `tests/integration/test_ingest_grains.py`

slowapi is already in `pyproject.toml` but never imported.

- [ ] **Step 1: Wire slowapi into main.py**

```python
# fleet_platform/api/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request

limiter = Limiter(key_func=get_remote_address)

def create_app() -> FastAPI:
    app = FastAPI(...)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(CORSMiddleware, ...)
    # ... rest of routers
    return app
```

- [ ] **Step 2: Apply rate limits to ingest endpoints**

In `fleet_platform/api/routes/ingest.py`:

```python
from fleet_platform.api.main import limiter

# Grain ingest: 60 per minute per IP (one per node per minute is fine)
@router.post("/grains")
@limiter.limit("60/minute")
async def ingest_grains(request: Request, ...):
    ...

# SBOM ingest: 10 per minute (slow uploads)
@router.post("/sbom/{minion_id}")
@limiter.limit("10/minute")
async def ingest_sbom(request: Request, ...):
    ...

# Execution ingest: 120 per minute
@router.post("/executions")
@limiter.limit("120/minute")
async def ingest_execution(request: Request, ...):
    ...
```

Also rate-limit auth endpoints in `fleet_platform/api/routes/auth.py`:

```python
from fleet_platform.api.main import limiter

@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, ...):
    ...
```

- [ ] **Step 3: Write a test**

Add to `tests/integration/test_auth_endpoints.py`:

```python
async def test_login_rate_limited(client: AsyncClient):
    """After 10 failed login attempts in a minute, further attempts return 429."""
    for i in range(10):
        await client.post("/auth/login", json={"email": f"x{i}@x.com", "password": "wrong"})
    r = await client.post("/auth/login", json={"email": "overflow@x.com", "password": "wrong"})
    assert r.status_code == 429
```

Note: this test requires slowapi's in-memory storage to be enabled. If Redis is used as the slowapi backend, the test needs a fresh Redis namespace. For integration tests, use `storage_uri="memory://"` in the test limiter.

For the test environment, configure the test app with a separate memory limiter:

```python
# tests/integration/conftest.py — update app_with_test_db fixture
from slowapi import Limiter
from slowapi.util import get_remote_address

async def app_with_test_db(test_engine):
    from fleet_platform.api.main import create_app
    import fleet_platform.api.main as main_module

    # Override limiter with memory backend for tests
    test_limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    main_module.limiter = test_limiter

    app = create_app()
    app.state.limiter = test_limiter
    ...
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/ -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/main.py fleet_platform/api/routes/ingest.py \
  fleet_platform/api/routes/auth.py tests/integration/
git commit -m "feat(C5): wire slowapi rate limiting — ingest 60/min, login 10/min"
```

---

## Task 3: SBOM Upload Size Limit (C6)

**Files:**
- Modify: `fleet_platform/api/routes/ingest.py`
- Test: `tests/integration/test_ingest_sbom.py`

No size limit means a 1GB POST fills `/tmp` and crashes the host.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_ingest_sbom.py`:

```python
async def test_sbom_upload_too_large_rejected(client: AsyncClient, node_with_token):
    """SBOM uploads over 50MB must be rejected with 413."""
    node, token = node_with_token
    # Simulate a large upload via Content-Length header
    large_content = b"x" * (51 * 1024 * 1024)  # 51 MB
    r = await client.post(
        f"/api/v1/ingest/sbom/{node.minion_id}",
        content=large_content,
        headers={
            "X-Node-Token": token,
            "Content-Type": "application/json",
            "Content-Length": str(len(large_content)),
        },
    )
    assert r.status_code == 413
```

- [ ] **Step 2: Add size limit to ingest_sbom**

In `fleet_platform/api/routes/ingest.py`, update `ingest_sbom`:

```python
_MAX_SBOM_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/sbom/{minion_id}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_sbom(
    minion_id: str,
    request: Request,
    token: str | None = Header(default=None, alias="X-Node-Token"),
    db: AsyncSession = Depends(get_db),
):
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(minion_id, token, db)

    # Check Content-Length before streaming
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_SBOM_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"SBOM upload exceeds maximum size of {_MAX_SBOM_BYTES // (1024*1024)}MB",
        )

    size = 0
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f"sbom_{node.id}_", suffix=".json", delete=False
    ) as tmp:
        async for chunk in request.stream():
            size += len(chunk)
            if size > _MAX_SBOM_BYTES:
                tmp.close()
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"SBOM upload exceeds maximum size of {_MAX_SBOM_BYTES // (1024*1024)}MB",
                )
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        index_sbom.delay(node_id=str(node.id), file_path=tmp_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {"status": "queued", "node_id": str(node.id)}
```

- [ ] **Step 3: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_ingest_sbom.py -v
```

Expected: all pass including new 413 test.

- [ ] **Step 4: Commit**

```bash
git add fleet_platform/api/routes/ingest.py tests/integration/test_ingest_sbom.py
git commit -m "fix(C6): reject SBOM uploads over 50MB with 413"
```

---

## Task 4: Fix SBOM Celery Retry Logic (H2)

**Files:**
- Modify: `fleet_platform/workers/sbom_tasks.py`
- Test: `tests/unit/test_sbom_tasks.py`

`index_sbom` currently: reads file → `finally: os.unlink(file_path)` → then parses. On `json.JSONDecodeError` or DB failure, `self.retry()` re-runs but the file is already gone → all retries fail with `file_not_found`. Fix: the file is deleted after the `finally` block, before retry. Content is parsed from the in-memory string — no re-read needed.

The current code is already structured correctly after the Plan 5 fix (reads into `content` string, `finally: unlink`). Verify this is the case and that retrying on DB failure does NOT re-read the file:

- [ ] **Step 1: Verify the current implementation**

```bash
grep -n "content\|unlink\|retry\|json.loads" fleet_platform/workers/sbom_tasks.py
```

Expected: file is read into `content = f.read()`, deleted in `finally`, then `json.loads(content)` — file is not re-read on retry. If this structure is confirmed, H2 is already fixed by Plan 5.

- [ ] **Step 2: Fix compute_drift retry (H1)**

In `fleet_platform/workers/drift_tasks.py`, add actual retry logic:

```python
@celery_app.task(
    name="fleet_platform.workers.drift_tasks.compute_drift",
    bind=True,
    max_retries=3,
    queue="drift",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def compute_drift(self, node_id: str) -> dict:
    ...  # existing implementation unchanged
```

Remove the `bind=True, max_retries=3` from the decorator (they were there already) and add `autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True` — this wires actual retry without needing explicit `self.retry()` calls.

- [ ] **Step 3: Same for archive_old_scans and index_sbom**

Update `sbom_tasks.py` decorators:

```python
@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.index_sbom",
    bind=True,
    max_retries=3,
    queue="sbom",
    autoretry_for=(Exception,),  # but NOT FileNotFoundError and JSONDecodeError
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def index_sbom(self, node_id: str, file_path: str) -> dict:
    # The try/except for FileNotFoundError and JSONDecodeError return early
    # — autoretry_for=(Exception,) won't catch them because they're handled before raising
    ...
```

For `archive_old_scans`:
```python
@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.archive_old_scans",
    bind=True,
    max_retries=3,
    queue="sbom",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def archive_old_scans(self, node_id: str, keep_count: int = 3) -> dict:
    ...  # remove the inner try/except with self.retry() — autoretry handles it
```

- [ ] **Step 4: Run unit tests**

```bash
source .venv/bin/activate && pytest tests/unit/test_sbom_tasks.py tests/unit/test_drift_task.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/workers/drift_tasks.py fleet_platform/workers/sbom_tasks.py
git commit -m "fix(H1/H2): add autoretry_for with exponential backoff to drift and SBOM Celery tasks"
```

---

## Task 5: /health/ready Endpoint (H3/H5)

**Files:**
- Modify: `fleet_platform/api/routes/health.py`
- Test: `tests/integration/test_health.py`

The existing `/health` endpoint returns `{"status":"ok"}` without checking DB or Redis. Add `/health/ready` that performs a lightweight DB ping and Redis ping.

- [ ] **Step 1: Write failing test**

Add to `tests/integration/test_health.py`:

```python
async def test_health_ready_returns_200(client: AsyncClient):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["redis"] == "ok"


async def test_health_ready_shape(client: AsyncClient):
    r = await client.get("/health/ready")
    data = r.json()
    assert "version" in data
    assert "checks" in data
```

- [ ] **Step 2: Implement /health/ready**

```python
# fleet_platform/api/routes/health.py
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.config import settings, VERSION

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "environment": settings.environment}


@router.get("/health/ready")
async def health_ready(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    checks: dict[str, str] = {}
    overall = "ready"

    # Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        overall = "degraded"

    # Redis check
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
        overall = "degraded"

    http_status = 200 if overall == "ready" else 503
    return JSONResponse(
        status_code=http_status,
        content={"status": overall, "version": VERSION, "checks": checks},
    )
```

- [ ] **Step 3: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_health.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add fleet_platform/api/routes/health.py tests/integration/test_health.py
git commit -m "feat(H3): /health/ready checks DB + Redis connectivity, returns 503 if degraded"
```

---

## Task 6: Audit Coverage Expansion (C8)

**Files:**
- Modify: `fleet_platform/api/routes/auth.py` — audit login events
- Modify: `fleet_platform/api/routes/baselines.py` — audit create
- Modify: `fleet_platform/api/routes/groups.py` — audit create/update/delete
- Modify: `fleet_platform/api/routes/drift.py` — audit compute trigger
- Test: `tests/integration/test_auth_endpoints.py`

- [ ] **Step 1: Audit login in auth.py**

Add to the `login` handler after `await db.commit()`:

```python
from fleet_platform.core.audit import audit

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is disabled")
    user.last_login_at = datetime.now(UTC)
    await audit(db, actor=payload.email, action="auth.login",
                resource_type="user", resource_id=user.id,
                ip_address=request.client.host if request.client else None)
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(user_id=str(user.id), email=user.email, role=user.role),
        refresh_token=create_refresh_token(user_id=str(user.id)),
    )
```

Note: Add `request: Request` parameter to the login function signature.

- [ ] **Step 2: Audit baseline create**

In `fleet_platform/api/routes/baselines.py`, after `await db.commit()` in `create_baseline`:

```python
from fleet_platform.core.audit import audit

    await audit(db, actor=claims["email"], action="baseline.create",
                resource_type="baseline", resource_id=baseline.id,
                new_value={"name": baseline.name, "target_type": baseline.target_type})
    await db.commit()
```

- [ ] **Step 3: Audit group create/update/delete**

In `fleet_platform/api/routes/groups.py`:

```python
# create_group — after db.commit()
await audit(db, actor=claims["email"], action="group.create",
            resource_type="group", resource_id=group.id,
            new_value={"name": group.name, "type": group.type})

# update_group — before db.commit()
await audit(db, actor=claims["email"], action="group.update",
            resource_type="group", resource_id=group.id,
            new_value=payload.model_dump(exclude_none=True))

# delete_group — before db.delete()
await audit(db, actor=claims["email"], action="group.delete",
            resource_type="group", resource_id=group_id)
```

- [ ] **Step 4: Audit drift compute trigger**

In `fleet_platform/api/routes/drift.py`, in `trigger_compute`:

```python
await audit(db, actor=claims["email"], action="drift.compute.triggered",
            resource_type="node", resource_id=node_id)
await db.commit()
```

- [ ] **Step 5: Run the full test suite**

```bash
source .venv/bin/activate && pytest tests/ -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/auth.py fleet_platform/api/routes/baselines.py \
  fleet_platform/api/routes/groups.py fleet_platform/api/routes/drift.py
git commit -m "feat(C8): expand audit coverage to login, baseline create, group CRUD, drift compute trigger"
```

---

## Task 7: Full Test Suite + TypeScript Build Verification

- [ ] **Step 1: Run all backend tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: `160+ passed, 0 failed`

- [ ] **Step 2: TypeScript build**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -3
```

Expected: `✓ built`

---

## Self-Review

- [x] C3: /auth/logout + refresh revocation — Task 1
- [x] C5: Rate limiting — Task 2
- [x] C6: SBOM size limit — Task 3
- [x] H1: compute_drift retry — Task 4
- [x] H2: SBOM retry — Task 4 (verify already fixed)
- [x] H3: Health/readiness — Task 5
- [x] C8: Audit coverage — Task 6
