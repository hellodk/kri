# Audit Page, Drift Fix, Settings Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 issues simultaneously: (1) create Audit page + backend route, (2) add PATCH /baselines/{id} endpoint and fix drift baseline schema, (3) add Settings page tab layout, (4) verify SBOM list endpoint is correct.

**Architecture:** Backend routes are FastAPI routers in `fleet_platform/api/routes/`. Frontend pages are React components in `frontend/src/pages/`. The audit model is `AuditEvent` in `fleet_platform/models/audit.py` with fields: `id`, `event_at`, `actor`, `action`, `resource_type`, `resource_id`, `old_value`, `new_value`, `ip_address`. The drift compute endpoint already exists at `POST /api/v1/drift/{node_id}/compute`. SBOM is fine — it has `/api/v1/sbom/search` and per-node routes, which is exactly what SBOMExplorer.tsx uses.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), React + TanStack Query + Tailwind (frontend), TypeScript

---

## File Map

**Create:**
- `fleet_platform/api/routes/audit.py` — GET /api/v1/audit paginated endpoint
- `frontend/src/pages/AuditPage.tsx` — Audit log table with filters and pagination
- `frontend/src/api/audit.ts` — API client for audit endpoint

**Modify:**
- `fleet_platform/api/routes/baselines.py` — add PATCH /{baseline_id} endpoint
- `fleet_platform/api/main.py` — import and register audit router
- `frontend/src/App.tsx` — add /audit route
- `frontend/src/pages/SettingsPage.tsx` — add 5-tab layout

---

## Task 1: Backend — GET /api/v1/audit endpoint

**Files:**
- Create: `fleet_platform/api/routes/audit.py`

- [ ] **Step 1: Read the AuditEvent model fields**

The model at `fleet_platform/models/audit.py` uses class `AuditEvent` with table `audit_events`. Fields confirmed: `id` (BigInteger), `event_at` (DateTime), `actor` (String), `action` (String), `resource_type` (String, nullable), `resource_id` (UUID, nullable), `old_value` (JSONB, nullable), `new_value` (JSONB, nullable), `ip_address` (INET, nullable).

- [ ] **Step 2: Create `fleet_platform/api/routes/audit.py`**

```python
# fleet_platform/api/routes/audit.py
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.audit import AuditEvent
from fleet_platform.schemas.common import PaginatedResponse

router = APIRouter(prefix="/api/v1/audit")


class AuditEventResponse(BaseModel):
    id: int
    event_at: datetime
    actor: str
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    ip_address: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=PaginatedResponse[AuditEventResponse])
async def list_audit_logs(
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(AuditEvent)

    if actor:
        query = query.where(AuditEvent.actor.ilike(f"%{actor}%"))
    if action:
        query = query.where(AuditEvent.action.ilike(f"%{action}%"))
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = query.order_by(AuditEvent.event_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    events = result.scalars().all()

    return PaginatedResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        per_page=per_page,
    )
```

- [ ] **Step 3: Register audit router in `fleet_platform/api/main.py`**

Add the import after the existing route imports:
```python
from fleet_platform.api.routes.audit import router as audit_router
```

Add the include_router call after the last existing `include_router` line:
```python
app.include_router(audit_router, tags=["audit"])
```

The final import block in `main.py` will look like:
```python
from fleet_platform.api.routes import (
    health, auth, nodes, ingest, fleet, groups, search, baselines, drift, executions, sbom,
    ansible, platform_settings
)
from fleet_platform.api.routes.provisioning import router as provisioning_router
from fleet_platform.api.routes.security import router as security_router
from fleet_platform.api.routes.webssh import router as webssh_router
from fleet_platform.api.routes.vnc import router as vnc_router
from fleet_platform.api.routes.audit import router as audit_router
```

And in `create_app()`:
```python
app.include_router(vnc_router, tags=["vnc"])
app.include_router(audit_router, tags=["audit"])
```

- [ ] **Step 4: Verify no syntax errors**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate && python -c "from fleet_platform.api.routes.audit import router; print('OK')"
```

Expected: `OK`

---

## Task 2: Backend — PATCH /api/v1/baselines/{baseline_id}

**Files:**
- Modify: `fleet_platform/api/routes/baselines.py`

- [ ] **Step 1: Add PATCH endpoint at end of `fleet_platform/api/routes/baselines.py`**

Append after the existing `get_baseline` endpoint (line 123):

```python

@router.patch("/{baseline_id}", response_model=BaselineResponse)
async def update_baseline(
    baseline_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    from fleet_platform.core.audit import audit
    result = await db.execute(
        select(DesiredStateBaseline).where(DesiredStateBaseline.id == baseline_id)
    )
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
    if "name" in payload:
        baseline.name = payload["name"]
    if "state_json" in payload:
        baseline.state_json = payload["state_json"]
        baseline.version = baseline.version + 1
    if "description" in payload:
        baseline.description = payload["description"]
    await audit(db, actor=claims["email"], action="baseline.update",
                resource_type="baseline", resource_id=baseline_id,
                new_value={"name": baseline.name})
    await db.commit()
    await db.refresh(baseline)
    return BaselineResponse.model_validate(baseline)
```

Note: `require_role` is already imported in baselines.py. `select`, `DesiredStateBaseline`, `HTTPException`, `status`, `BaselineResponse` are all already imported.

- [ ] **Step 2: Verify no syntax errors**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate && python -c "from fleet_platform.api.routes.baselines import router; print('OK')"
```

Expected: `OK`

---

## Task 3: Frontend — audit API client

**Files:**
- Create: `frontend/src/api/audit.ts`

- [ ] **Step 1: Create `frontend/src/api/audit.ts`**

```typescript
import { api } from './client'

export interface AuditEvent {
  id: number
  event_at: string
  actor: string
  action: string
  resource_type: string | null
  resource_id: string | null
  ip_address: string | null
}

export interface AuditListParams {
  actor?: string
  action?: string
  resource_type?: string
  page?: number
  per_page?: number
}

export interface AuditListResponse {
  items: AuditEvent[]
  total: number
  page: number
  per_page: number
}

export const auditApi = {
  list: (params: AuditListParams = {}) => {
    const q = new URLSearchParams()
    if (params.actor) q.set('actor', params.actor)
    if (params.action) q.set('action', params.action)
    if (params.resource_type) q.set('resource_type', params.resource_type)
    if (params.page) q.set('page', String(params.page))
    if (params.per_page) q.set('per_page', String(params.per_page))
    return api.get<AuditListResponse>(`/api/v1/audit?${q}`)
  },
}
```

---

## Task 4: Frontend — AuditPage component

**Files:**
- Create: `frontend/src/pages/AuditPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/AuditPage.tsx`**

```tsx
import { useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi } from '../api/audit'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'

function actionBadgeClass(action: string): string {
  if (action.endsWith('.create')) return 'bg-green-100 text-green-700'
  if (action.endsWith('.delete') || action.includes('.block') || action.includes('security')) return 'bg-red-100 text-red-700'
  if (action.endsWith('.update')) return 'bg-blue-100 text-blue-700'
  if (action === 'auth.login') return 'bg-gray-100 text-gray-600'
  return 'bg-gray-100 text-gray-600'
}

export function AuditPage() {
  const [page, setPage] = useState(1)
  const [actorFilter, setActorFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [debouncedActor, setDebouncedActor] = useState('')
  const [debouncedAction, setDebouncedAction] = useState('')
  const actorTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const actionTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  function handleActor(value: string) {
    setActorFilter(value)
    clearTimeout(actorTimer.current)
    actorTimer.current = setTimeout(() => { setDebouncedActor(value); setPage(1) }, 400)
  }

  function handleAction(value: string) {
    setActionFilter(value)
    clearTimeout(actionTimer.current)
    actionTimer.current = setTimeout(() => { setDebouncedAction(value); setPage(1) }, 400)
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit', debouncedActor, debouncedAction, page],
    queryFn: () => auditApi.list({
      actor: debouncedActor || undefined,
      action: debouncedAction || undefined,
      page,
      per_page: 50,
    }),
    staleTime: 15_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>

      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="search"
          placeholder="Filter by actor email…"
          value={actorFilter}
          onChange={(e) => handleActor(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-56"
        />
        <input
          type="search"
          placeholder="Filter by action…"
          value={actionFilter}
          onChange={(e) => handleAction(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-48"
        />
        {data && <span className="text-sm text-gray-500">{data.total} events</span>}
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={12} />
        ) : isError ? (
          <ErrorState message="Failed to load audit log" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Resource Type</th>
                  <th className="px-4 py-3">Resource ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                      No audit events found
                    </td>
                  </tr>
                )}
                {data?.items.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                      {formatDistanceToNow(new Date(e.event_at), { addSuffix: true })}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700 max-w-[180px] truncate">
                      {e.actor}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium font-mono ${actionBadgeClass(e.action)}`}>
                        {e.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{e.resource_type ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                      {e.resource_id ? e.resource_id.slice(0, 8) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && (
              <Pagination
                page={page}
                total={data.total}
                perPage={data.per_page}
                onPage={setPage}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}
```

---

## Task 5: Wire AuditPage into App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add import and route to `frontend/src/App.tsx`**

Add import after the last import line (after `SecurityPage`):
```tsx
import { AuditPage } from './pages/AuditPage'
```

Add route inside the AuthGuard Routes block, after the `/security` route:
```tsx
<Route path="/audit" element={<AuditPage />} />
```

The final routes block (within AuthGuard) should include:
```tsx
<Route path="/security" element={<SecurityPage />} />
<Route path="/audit" element={<AuditPage />} />
<Route path="/settings" element={<SettingsPage />} />
```

- [ ] **Step 2: Verify the file compiles (TypeScript check runs in build)**

```bash
cd /home/dk/Documents/git/kri/frontend && grep -n "AuditPage" src/App.tsx
```

Expected: Two lines — the import and the Route.

---

## Task 6: Settings page — 5-tab layout

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Rewrite the SettingsPage render section**

The file has all state variables already (`master`, `kriApiUrl`, `username`, `password`, `showPassword`, `ansibleEndpoint`, `ansibleToken`, `playbooksDir`, `pillarDir`, `cxoneUrl`, `cxoneToken`, `sonarUrl`, `sonarToken`, `licensePolicy`, `vncEnabled`). Only the JSX returned by `SettingsPage` changes — everything from line 83 (`return (`) to line 399 (`}`) is replaced.

Replace the entire `return (...)` block of `SettingsPage` (lines 83-399, i.e., everything from `return (` through the closing `  )` before `}`) with:

```tsx
  const TABS = ['General', 'Bootstrap', 'Remote Access', 'Integrations', 'Advanced'] as const
  type Tab = typeof TABS[number]
  const [activeTab, setActiveTab] = useState<Tab>('General')

  if (isLoading) return <div className="p-6 text-gray-500">Loading…</div>

  const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600'
  const monoInputClass = inputClass + ' font-mono'

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure the kri fleet platform.</p>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200">
        {TABS.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === tab
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* General tab */}
      {activeTab === 'General' && (
        <div className="space-y-6">
          {/* kri External URL */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">kri External URL</h2>
              <p className="text-sm text-gray-500 mt-1">
                The URL that Mac Minis use to call back to this kri server. Used to build the ingest endpoint
                that Salt minions POST grain data to. Must be reachable from all managed nodes — use the
                Tailscale IP or a LAN address, not <code className="text-xs bg-gray-100 px-1 rounded">localhost</code>.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">kri server URL</label>
              <input
                type="text"
                value={kriApiUrl}
                onChange={(e) => setKriApiUrl(e.target.value)}
                placeholder="http://100.89.50.27  or  http://kri.fleet.local"
                className={monoInputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Include the scheme (<code>http://</code> or <code>https://</code>). No trailing slash.</p>
            </div>
            {computedIngestUrl && (
              <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2">
                <span className="text-xs text-gray-400 shrink-0">Computed ingest URL:</span>
                <code className="text-xs font-mono text-brand-700 truncate">{computedIngestUrl}</code>
              </div>
            )}
          </div>

          {/* Salt Master */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Salt Master</h2>
              <p className="text-sm text-gray-500 mt-1">
                Hostname or IP of the Salt master. Written into <code className="text-xs bg-gray-100 px-1 rounded">/etc/salt/minion</code> on each node during bootstrap.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Master address (IP or DNS, no port)</label>
              <input
                type="text"
                value={master}
                onChange={(e) => setMaster(e.target.value)}
                placeholder="100.89.50.27  or  salt.fleet.local"
                className={monoInputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Salt minions connect to this on port 4505/4506.</p>
            </div>
          </div>
        </div>
      )}

      {/* Bootstrap tab */}
      {activeTab === 'Bootstrap' && (
        <div className="space-y-6">
          {/* SSH Bootstrap credentials */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Default SSH Bootstrap Credentials</h2>
              <p className="text-sm text-gray-500 mt-1">
                Used as fallback when a node has no per-node SSH credentials set.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">macOS admin username</label>
              <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                placeholder="localadmin" className={inputClass} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                macOS admin password
                <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted, not shown after save)</span>
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Leave blank to keep existing"
                  className={inputClass + ' pr-16'}
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1">
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Controller SSH public key */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-3">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Controller SSH Public Key</h2>
              <p className="text-sm text-gray-500 mt-1">
                Auto-generated key deployed to all Mac Minis during bootstrap via{' '}
                <code className="text-xs bg-gray-100 px-1 rounded">authorized_key</code>.
              </p>
            </div>
            {data?.controller_pubkey ? (
              <div className="relative">
                <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto text-gray-700 whitespace-pre-wrap break-all">
                  {data.controller_pubkey}
                </pre>
                <button
                  onClick={() => { navigator.clipboard.writeText(data.controller_pubkey!); toast('Copied') }}
                  className="absolute top-2 right-2 text-xs text-gray-400 hover:text-gray-600 bg-white border border-gray-200 rounded px-2 py-0.5"
                >
                  Copy
                </button>
              </div>
            ) : (
              <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                No keypair generated yet. Save settings once to generate the controller keypair.
              </p>
            )}
          </div>

          {/* Pillar directory */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Salt Pillar Directory</h2>
              <p className="text-sm text-gray-500 mt-1">
                kri writes a per-node <code className="text-xs bg-gray-100 px-1 rounded">&lt;minion_id&gt;.sls</code> file here before every bootstrap.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Path to Salt pillar directory</label>
              <input type="text" value={pillarDir} onChange={(e) => setPillarDir(e.target.value)}
                placeholder="/srv/salt/pillar  (default)"
                className={monoInputClass} />
              <p className="text-xs text-gray-400 mt-1">Must be writable by the kri process.</p>
            </div>
          </div>

          {/* Playbooks directory */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Playbooks Directory</h2>
              <p className="text-sm text-gray-500 mt-1">Override the directory kri scans for Ansible playbooks and roles.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Path to playbooks &amp; roles</label>
              <input type="text" value={playbooksDir} onChange={(e) => setPlaybooksDir(e.target.value)}
                placeholder="/home/user/my-playbooks  (default: <repo>/playbooks)"
                className={monoInputClass} />
              <p className="text-xs text-gray-400 mt-1">
                Roles must be in a <code>roles/</code> subdirectory.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Remote Access tab */}
      {activeTab === 'Remote Access' && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Remote Access</h2>
              <p className="text-sm text-gray-500 mt-1">
                Control which remote access methods are available to operators.
                Changes take effect immediately after saving.
              </p>
            </div>

            <div className="flex items-center justify-between py-3 border-b border-gray-100">
              <div>
                <p className="text-sm font-medium text-gray-900">WebSSH Terminal</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Browser-based SSH with keystroke recording and command blocking.
                  Always enabled — cannot be disabled.
                </p>
              </div>
              <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded font-medium">Always on</span>
            </div>

            <div className="flex items-center justify-between py-3">
              <div>
                <p className="text-sm font-medium text-gray-900">VNC Screen Share</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Full graphical desktop access via browser (noVNC). Requires Screen Sharing
                  to be enabled on the Mac Mini. Sessions are logged but <strong>cannot be command-blocked</strong>.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setVncEnabled(!vncEnabled)}
                className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                  vncEnabled ? 'bg-brand-600' : 'bg-gray-300'
                }`}
                role="switch"
                aria-checked={vncEnabled}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                    vncEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {vncEnabled && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700">
                VNC sessions are recorded but commands cannot be blocked (graphical pixel stream).
                Ensure your security policy allows unfiltered screen access before enabling.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Integrations tab */}
      {activeTab === 'Integrations' && (
        <div className="space-y-6">
          {/* Security Integrations */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Security Integrations</h2>
              <p className="text-sm text-gray-500 mt-1">
                Connect Checkmarx One (CxOne) and SonarQube for enhanced vulnerability and license scanning.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">CxOne URL</label>
                <input type="text" value={cxoneUrl} onChange={e => setCxoneUrl(e.target.value)}
                  placeholder="https://us.cxone.net" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  CxOne API Token <span className="text-xs text-gray-400 font-normal">(encrypted)</span>
                </label>
                <input type="password" value={cxoneToken} onChange={e => setCxoneToken(e.target.value)}
                  placeholder="Leave blank to keep existing" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">SonarQube URL</label>
                <input type="text" value={sonarUrl} onChange={e => setSonarUrl(e.target.value)}
                  placeholder="http://sonarqube.utilities.svc.cluster.local:9000" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  SonarQube Token <span className="text-xs text-gray-400 font-normal">(encrypted)</span>
                </label>
                <input type="password" value={sonarToken} onChange={e => setSonarToken(e.target.value)}
                  placeholder="Leave blank to keep existing" className={inputClass} />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">License Policy</label>
              <select value={licensePolicy} onChange={e => setLicensePolicy(e.target.value)} className={inputClass}>
                <option value="permissive">Permissive - flag GPL only</option>
                <option value="strict">Strict - flag GPL + LGPL + unknown</option>
              </select>
              <p className="text-xs text-gray-400 mt-1">Controls which licenses are flagged as "high risk" in the Security dashboard.</p>
            </div>
          </div>

          {/* External Ansible endpoint */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">External Ansible Endpoint</h2>
              <p className="text-sm text-gray-500 mt-1">
                Configure an AWX or Ansible Tower endpoint. When set, kri sends playbook jobs to this endpoint instead of running <code className="text-xs bg-gray-100 px-1 rounded">ansible-runner</code> locally.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Endpoint URL</label>
              <input type="text" value={ansibleEndpoint} onChange={(e) => setAnsibleEndpoint(e.target.value)}
                placeholder="https://awx.example.com" className={inputClass} />
              <p className="text-xs text-gray-400 mt-1">Leave blank to use local ansible-runner.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                API Token <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted)</span>
              </label>
              <input type="password" value={ansibleToken} onChange={(e) => setAnsibleToken(e.target.value)}
                placeholder="Leave blank to keep existing" className={inputClass} />
            </div>
          </div>
        </div>
      )}

      {/* Advanced tab */}
      {activeTab === 'Advanced' && (
        <div className="space-y-6">
          <PlaybookSourcesSection />
        </div>
      )}

      {/* Save button — always visible */}
      <div className="flex justify-end pt-2">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="px-6 py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
```

**Important:** The `[activeTab, setActiveTab]` state must be declared inside `SettingsPage`, before the `return` statement, alongside the existing state variables. The `isLoading` guard and `inputClass`/`monoInputClass` declarations also move inside the new return block (or stay just before it — they were already before the return). The new code adds `const [activeTab, setActiveTab] = useState<Tab>('General')` and the `TABS`/`Tab` declarations just before `if (isLoading)`.

The exact edit: In `SettingsPage.tsx`, find the block starting with `if (isLoading) return <div className="p-6 text-gray-500">Loading…</div>` (line 78) and replace everything from that line through the closing `)` of the return statement (line 399) with the content above.

**Step-by-step edit guidance:**

The string to find (old_string for the Edit tool) starts at line 78:
```
  if (isLoading) return <div className="p-6 text-gray-500">Loading…</div>

  const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600'
  const monoInputClass = inputClass + ' font-mono'

  return (
    <div className="space-y-8 max-w-2xl">
```

Replace with the new tab layout shown above (everything from `const TABS = ...` through the closing `</div>\n  )\n`).

---

## Task 7: Build frontend + rebuild API container

**Files:** None (build commands only)

- [ ] **Step 1: Build frontend**

```bash
cd /home/dk/Documents/git/kri/frontend && npm run build 2>&1 | tail -15
```

Expected: Build succeeds with no TypeScript errors. Last lines show `dist/` file sizes.

- [ ] **Step 2: Rebuild API container**

```bash
docker compose -f /home/dk/Documents/git/kri/deploy/docker-compose.yml build api 2>&1 | tail -5
```

Expected: `Successfully built` or `=> exporting to image`.

- [ ] **Step 3: Restart API and frontend containers**

```bash
docker compose -f /home/dk/Documents/git/kri/deploy/docker-compose.yml up -d api frontend 2>&1 | tail -5
```

Expected: Containers started/recreated.

---

## Task 8: Fix baseline state_json and trigger drift

**Files:** None (runtime API calls)

- [ ] **Step 1: Get auth token and baseline ID**

```bash
sleep 10
TOKEN=$(curl -s -X POST http://localhost/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:20}..."

BL_ID=$(curl -s "http://localhost/api/v1/baselines?per_page=5" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; items=json.load(sys.stdin).get('items',[]); print(items[0]['id'] if items else 'NONE')")
echo "Baseline ID: $BL_ID"
```

Expected: Token starts with `eyJ...`, BL_ID is a UUID.

- [ ] **Step 2: Patch baseline with correct state_json schema**

```bash
curl -s -X PATCH "http://localhost/api/v1/baselines/$BL_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"state_json":{"packages":{"required":[{"name":"salt","version":">=3006.0"},{"name":"git","version":">=2.0.0"}],"forbidden":[]},"services":{"required_running":["salt-minion"],"required_stopped":[]}}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('Updated:', d.get('name'), '| version:', d.get('version'))"
```

Expected: `Updated: <baseline name> | version: 2` (version increments).

- [ ] **Step 3: Trigger drift compute for both nodes**

```bash
for SEARCH in mm3 mm1; do
  NID=$(curl -s "http://localhost/api/v1/nodes?search=$SEARCH" \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json; items=json.load(sys.stdin).get('items',[]); print(items[0]['id'] if items else '')")
  if [ -n "$NID" ]; then
    RESULT=$(curl -s -X POST "http://localhost/api/v1/drift/$NID/compute" \
      -H "Authorization: Bearer $TOKEN")
    echo "Drift triggered for $SEARCH ($NID): $RESULT"
  else
    echo "No node found for search: $SEARCH"
  fi
done
```

Expected: `{"status": "queued", "node_id": "..."}` for each node found.

---

## Task 9: Commit

**Files:** All modified files

- [ ] **Step 1: Stage all changed files**

```bash
cd /home/dk/Documents/git/kri && git add \
  fleet_platform/api/routes/audit.py \
  fleet_platform/api/routes/baselines.py \
  fleet_platform/api/main.py \
  frontend/src/api/audit.ts \
  frontend/src/pages/AuditPage.tsx \
  frontend/src/pages/SettingsPage.tsx \
  frontend/src/App.tsx
```

- [ ] **Step 2: Commit**

```bash
cd /home/dk/Documents/git/kri && git commit -m "$(cat <<'EOF'
fix: audit page, drift baseline PATCH, settings tabs

- AuditPage: table with actor/action/resource, color-coded action badges,
  filter by actor and action, paginated (GET /api/v1/audit)
- GET /api/v1/audit: paginated audit log endpoint with actor/action filters
- PATCH /api/v1/baselines/{id}: update name/state_json/description + version bump
- POST /api/v1/drift/{id}/compute: already existed, baseline schema corrected
- SettingsPage: 5-tab layout (General, Bootstrap, Remote Access,
  Integrations, Advanced) — CxOne/SonarQube/Ansible in Integrations tab

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds with the new SHA.

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| GET /api/v1/audit paginated with filters | Task 1 |
| Register audit router in main.py | Task 1 |
| AuditPage with table, filters, badges, pagination | Task 4 |
| frontend/src/api/audit.ts client | Task 3 |
| Wire /audit route in App.tsx | Task 5 |
| PATCH /api/v1/baselines/{id} | Task 2 |
| Fix baseline state_json schema via API | Task 8 |
| Trigger compute_drift for both nodes | Task 8 |
| Settings 5-tab layout | Task 6 |
| PlaybookSourcesSection in Advanced tab | Task 6 |
| Save button always visible | Task 6 |
| Build + deploy | Task 7 |
| Commit | Task 9 |

**SBOM check:** The spec mentions checking SBOM. SBOMExplorer.tsx uses `sbomApi.search(debouncedQ)` which calls `/api/v1/sbom/search`. The backend has `GET /api/v1/sbom/search`. This matches — no fix needed for SBOM.

**Placeholder scan:** No TBD/TODO/placeholder patterns found.

**Type consistency:** 
- `AuditEventResponse` fields used in `AuditPage.tsx` (`id`, `event_at`, `actor`, `action`, `resource_type`, `resource_id`) match `audit.ts` interface exactly.
- `Pagination` component props (`page`, `total`, `perPage`, `onPage`) match usage in `AuditPage.tsx`.
- `BaselineResponse` already has `version` field (verified in schemas/drift.py), so PATCH response works.

**Note on SettingsPage edit:** The `useState<Tab>` declaration needs `Tab` type which is defined just above it as `type Tab = typeof TABS[number]`. Both must be inside the function body, before `if (isLoading)`. The full replacement in Task 6 shows this correctly.
