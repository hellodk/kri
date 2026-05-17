# Audit Fix Plan 10 — Frontend Improvements & Alerting

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four frontend improvements (mutation feedback toasts, execution target hostname, sidebar icon collapse, audit log page) plus a backend webhook alerting system for node offline and critical drift events.

**Architecture:** Toast notifications use a lightweight Zustand store (no new library — simple stack of messages with auto-dismiss). Alerting uses a new `webhook_configs` table and a Celery beat task that polls for alert conditions every 5 minutes and fires HTTP POSTs. No external dependencies beyond what's already installed.

**Tech Stack:** React 18, TypeScript 5, Zustand 4, TanStack Query 5, Python 3.13, FastAPI 0.115, Celery 5.4, SQLAlchemy 2.0.

---

## Task 1: Toast Notification System (M10)

**Files:**
- Create: `frontend/src/stores/toastStore.ts`
- Create: `frontend/src/components/ToastContainer.tsx`
- Modify: `frontend/src/components/Layout/Layout.tsx` — mount ToastContainer
- Modify: `frontend/src/pages/NodeDetail.tsx` — show toasts on tag add/remove/drift trigger

- [ ] **Step 1: Create toast store**

```typescript
// frontend/src/stores/toastStore.ts
import { create } from 'zustand'

export interface Toast {
  id: string
  message: string
  type: 'success' | 'error' | 'info'
}

interface ToastState {
  toasts: Toast[]
  add: (message: string, type?: Toast['type']) => void
  remove: (id: string) => void
}

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  add: (message, type = 'success') => {
    const id = Math.random().toString(36).slice(2)
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4000)
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
```

- [ ] **Step 2: Create ToastContainer component**

```tsx
// frontend/src/components/ToastContainer.tsx
import { useToastStore } from '../stores/toastStore'

export function ToastContainer() {
  const { toasts, remove } = useToastStore()
  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-sm text-white min-w-64 max-w-sm ${
            t.type === 'success' ? 'bg-green-600' :
            t.type === 'error'   ? 'bg-red-600'   : 'bg-gray-700'
          }`}
        >
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => remove(t.id)}
            className="text-white/70 hover:text-white ml-2"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Mount in Layout.tsx**

```tsx
// frontend/src/components/Layout/Layout.tsx
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { ToastContainer } from '../ToastContainer'

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
      <ToastContainer />
    </div>
  )
}
```

- [ ] **Step 4: Add toasts to NodeDetail mutations**

In `frontend/src/pages/NodeDetail.tsx`, import and use the toast store:

```tsx
import { useToastStore } from '../stores/toastStore'

// Inside NodeDetail:
const toast = useToastStore((s) => s.add)

const addTagMutation = useMutation({
  mutationFn: () => fleetApi.addTag(nodeId!, tagKey, tagValue),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['node', nodeId] })
    setTagKey('')
    setTagValue('')
    toast('Tag added successfully')
  },
  onError: (err: Error) => toast(err.message, 'error'),
})

const removeTagMutation = useMutation({
  mutationFn: (key: string) => fleetApi.removeTag(nodeId!, key),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['node', nodeId] })
    toast('Tag removed')
  },
  onError: (err: Error) => toast(err.message, 'error'),
})

const computeMutation = useMutation({
  mutationFn: () => driftApi.compute(nodeId!),
  onSuccess: () => {
    toast('Drift computation queued')
    setTimeout(() => qc.invalidateQueries({ queryKey: ['drift-latest', nodeId] }), 3000)
  },
  onError: (err: Error) => toast(err.message, 'error'),
})
```

- [ ] **Step 5: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/stores/toastStore.ts frontend/src/components/ToastContainer.tsx \
  frontend/src/components/Layout/Layout.tsx frontend/src/pages/NodeDetail.tsx
git commit -m "feat(M10): toast notifications for tag add/remove and drift compute trigger"
```

---

## Task 2: Execution Target Hostname Resolution (M8)

**Files:**
- Modify: `fleet_platform/api/routes/executions.py` — include target hostname in response
- Modify: `fleet_platform/schemas/execution.py` — add `target_hostname` field
- Modify: `frontend/src/types/index.ts` — add field
- Modify: `frontend/src/pages/ExecutionHistory.tsx` — display hostname
- Modify: `frontend/src/pages/JobDetail.tsx` — display hostname

- [ ] **Step 1: Add target_hostname to ExecutionJobResponse**

```python
# fleet_platform/schemas/execution.py — add field
class ExecutionJobResponse(BaseModel):
    id: uuid.UUID
    salt_jid: str | None = None
    type: str
    target_type: str
    target_id: uuid.UUID | None = None
    target_hostname: str | None = None   # ← new
    triggered_by: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Join Node in list_executions and get_execution**

In `fleet_platform/api/routes/executions.py`:

```python
from fleet_platform.models.node import Node

@router.get("", response_model=PaginatedResponse[ExecutionJobResponse])
async def list_executions(...):
    ...
    result = await db.execute(query.offset(...).limit(...))
    jobs = result.scalars().all()

    # Resolve hostnames in one query
    node_ids = [j.target_id for j in jobs if j.target_id]
    hostname_map: dict[uuid.UUID, str | None] = {}
    if node_ids:
        nodes = (await db.execute(
            select(Node.id, Node.hostname).where(Node.id.in_(node_ids))
        )).all()
        hostname_map = {n.id: n.hostname for n in nodes}

    items = []
    for j in jobs:
        data = ExecutionJobResponse.model_validate(j)
        data.target_hostname = hostname_map.get(j.target_id) if j.target_id else None
        items.append(data)

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)
```

Apply the same pattern in `get_execution`.

- [ ] **Step 3: Update frontend type**

In `frontend/src/types/index.ts`:

```typescript
export interface ExecutionJob {
  id: string
  salt_jid: string | null
  type: string
  target_type: string
  target_id: string | null
  target_hostname: string | null   // ← add
  triggered_by: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
}
```

- [ ] **Step 4: Use hostname in ExecutionHistory and JobDetail**

In `frontend/src/pages/ExecutionHistory.tsx`, update the Target column:

```tsx
<td className="px-4 py-3 text-gray-600 text-xs">
  {j.target_hostname ?? (j.target_id ? j.target_id.slice(0, 8) : j.target_type)}
</td>
```

In `frontend/src/pages/JobDetail.tsx`, update the metadata grid:

```tsx
['Target', j.target_hostname ?? `${j.target_type}${j.target_id ? ':' + j.target_id.slice(0, 8) : ''}`],
```

- [ ] **Step 5: TypeScript check + backend tests**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
source /home/dk/Documents/git/kri/.venv/bin/activate && pytest tests/integration/test_executions_api.py -v
```

Expected: all pass, zero TS errors.

- [ ] **Step 6: Commit**

```bash
cd /home/dk/Documents/git/kri
git add fleet_platform/schemas/execution.py fleet_platform/api/routes/executions.py \
  frontend/src/types/index.ts frontend/src/pages/ExecutionHistory.tsx \
  frontend/src/pages/JobDetail.tsx
git commit -m "feat(M8): resolve target_hostname in execution responses"
```

---

## Task 3: Sidebar Icon Collapse Mode (M10)

**Files:**
- Modify: `frontend/src/components/Layout/Sidebar.tsx`
- Modify: `frontend/src/components/Layout/TopBar.tsx`

Currently toggling the sidebar hides it completely. Change to icon-only collapse (64px wide, show icons + tooltip).

- [ ] **Step 1: Update Sidebar.tsx**

```tsx
// frontend/src/components/Layout/Sidebar.tsx
import { NavLink } from 'react-router-dom'
import { useFilterStore } from '../../stores/filterStore'

const links = [
  { to: '/fleet',      label: 'Fleet',      icon: '🖥' },
  { to: '/drift',      label: 'Drift',      icon: '📊' },
  { to: '/sbom',       label: 'SBOM',       icon: '📦' },
  { to: '/groups',     label: 'Groups',     icon: '🗂' },
  { to: '/executions', label: 'Executions', icon: '⚡' },
  { to: '/audit',      label: 'Audit',      icon: '📋' },
]

export function Sidebar() {
  const open = useFilterStore((s) => s.sidebarOpen)

  return (
    <nav className={`flex-shrink-0 bg-gray-900 text-gray-100 min-h-screen flex flex-col transition-all duration-200 ${open ? 'w-56' : 'w-16'}`}>
      <div className={`px-4 py-5 border-b border-gray-700 overflow-hidden ${open ? '' : 'px-3'}`}>
        {open ? (
          <span className="text-lg font-bold tracking-tight text-white">Fleet Platform</span>
        ) : (
          <span className="text-lg text-white">🚀</span>
        )}
      </div>
      <ul className="flex-1 py-4 space-y-1">
        {links.map(({ to, label, icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              title={!open ? label : undefined}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  open ? '' : 'justify-center px-3'
                } ${
                  isActive
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              <span className="text-base">{icon}</span>
              {open && <span>{label}</span>}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/components/Layout/Sidebar.tsx
git commit -m "feat: sidebar icon-only collapse mode instead of full hide"
```

---

## Task 4: Audit Log Page (Frontend)

**Files:**
- Create: `frontend/src/pages/AuditLog.tsx`
- Modify: `frontend/src/App.tsx` — add `/audit` route
- Modify: `frontend/src/api/` — add audit API module
- Modify: `frontend/src/types/index.ts` — add AuditEvent type

- [ ] **Step 1: Add AuditEvent type**

```typescript
// frontend/src/types/index.ts — add
export interface AuditEvent {
  id: string
  event_at: string
  actor: string
  action: string
  resource_type: string | null
  resource_id: string | null
  ip_address: string | null
  new_value: Record<string, unknown> | null
  old_value: Record<string, unknown> | null
}
```

- [ ] **Step 2: Create audit API module**

```typescript
// frontend/src/api/audit.ts
import { api } from './client'
import type { AuditEvent, Paginated } from '../types'

export const auditApi = {
  list: (params?: {
    actor?: string
    action?: string
    resource_type?: string
    from?: string
    to?: string
    page?: number
    per_page?: number
  }) => {
    const q = new URLSearchParams()
    if (params?.actor) q.set('actor', params.actor)
    if (params?.action) q.set('action', params.action)
    if (params?.resource_type) q.set('resource_type', params.resource_type)
    if (params?.from) q.set('from', params.from)
    if (params?.to) q.set('to', params.to)
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<AuditEvent>>(`/api/v1/audit?${q}`)
  },
}
```

- [ ] **Step 3: Create AuditLog page**

```tsx
// frontend/src/pages/AuditLog.tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi } from '../api/audit'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { format } from 'date-fns'

const ACTION_GROUPS = ['', 'auth.login', 'node.tag.upsert', 'node.tag.delete',
  'node.decommission', 'group.create', 'group.update', 'group.delete',
  'baseline.create', 'drift.compute.triggered', 'user.create', 'user.update']

export function AuditLog() {
  const [page, setPage] = useState(1)
  const [actor, setActor] = useState('')
  const [action, setAction] = useState('')
  const [resourceType, setResourceType] = useState('')

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit', actor, action, resourceType, page],
    queryFn: () => auditApi.list({
      actor: actor || undefined,
      action: action || undefined,
      resource_type: resourceType || undefined,
      page,
      per_page: 50,
    }),
    staleTime: 10_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>

      <div className="flex flex-wrap gap-3">
        <input
          placeholder="Filter by actor (email)"
          value={actor}
          onChange={(e) => { setActor(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-3 py-1.5 w-56"
        />
        <select
          value={action}
          onChange={(e) => { setAction(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1.5"
        >
          <option value="">All actions</option>
          {ACTION_GROUPS.filter(Boolean).map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <input
          placeholder="Resource type (node, group…)"
          value={resourceType}
          onChange={(e) => { setResourceType(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-3 py-1.5 w-44"
        />
        {data && <span className="text-sm text-gray-500 self-center">{data.total} events</span>}
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? <Skeleton rows={10} /> : isError ? (
          <ErrorState message="Failed to load audit log" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Resource</th>
                  <th className="px-4 py-3">IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-500 font-mono text-xs whitespace-nowrap">
                      {format(new Date(e.event_at), 'MM/dd HH:mm:ss')}
                    </td>
                    <td className="px-4 py-2 text-gray-700">{e.actor}</td>
                    <td className="px-4 py-2">
                      <span className="font-mono text-xs bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">
                        {e.action}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-500 text-xs font-mono">
                      {e.resource_type && (
                        <span>{e.resource_type}{e.resource_id ? `:${e.resource_id.slice(0, 8)}` : ''}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-gray-400 text-xs">{e.ip_address ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && (
              <Pagination page={page} total={data.total} perPage={data.per_page} onPage={setPage} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add route to App.tsx**

```tsx
import { AuditLog } from './pages/AuditLog'
// Inside Routes:
<Route path="/audit" element={<AuditLog />} />
```

- [ ] **Step 5: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/AuditLog.tsx frontend/src/api/audit.ts \
  frontend/src/App.tsx frontend/src/types/index.ts
git commit -m "feat: Audit Log page — paginated event log with actor/action/resource filters"
```

---

## Task 5: Webhook Alerting for Node Offline + Critical Drift (M3)

**Files:**
- Create: `fleet_platform/db/migrations/versions/004_webhook_configs.py`
- Create: `fleet_platform/models/webhook.py`
- Create: `fleet_platform/api/routes/webhooks.py`
- Create: `fleet_platform/workers/alert_tasks.py`
- Modify: `fleet_platform/workers/celery_app.py` — add alert beat
- Modify: `fleet_platform/api/main.py` — register webhooks router
- Test: `tests/unit/test_alert_tasks.py`

- [ ] **Step 1: Create migration 004**

```python
# fleet_platform/db/migrations/versions/004_webhook_configs.py
"""Add webhook_configs table for alerting."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "webhook_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("events", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("webhook_configs")
```

Run:
```bash
source .venv/bin/activate && alembic upgrade head
```

- [ ] **Step 2: Create WebhookConfig model**

```python
# fleet_platform/models/webhook.py
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 3: Create alert_tasks.py**

```python
# fleet_platform/workers/alert_tasks.py
"""
Periodically checks for alert conditions and fires webhooks.
Events fired:
  - node.offline: node.status transitioned to 'offline' in the last beat interval
  - drift.critical: node.drift_score > 80 (checked each run; deduplicated via Redis)
"""
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.models.webhook import WebhookConfig
from fleet_platform.workers.celery_app import celery_app

_log = logging.getLogger(__name__)
_ALERT_DEDUP_TTL = 3600  # 1 hour — don't re-fire same alert for the same node
_CRITICAL_DRIFT_THRESHOLD = 80


def _dedup_key(redis, event: str, node_id: str) -> bool:
    """Returns True if this alert was already fired recently."""
    key = f"alert:dedup:{event}:{node_id}"
    if redis.exists(key):
        return True
    redis.setex(key, _ALERT_DEDUP_TTL, "1")
    return False


def _fire_webhook(url: str, payload: dict) -> None:
    try:
        httpx.post(url, json=payload, timeout=10)
    except Exception as e:
        _log.warning("Webhook delivery failed: %s url=%s", e, url)


@celery_app.task(name="fleet_platform.workers.alert_tasks.check_alerts", queue="maintenance")
def check_alerts() -> dict:
    import redis as _redis_sync
    from fleet_platform.core.config import settings
    r = _redis_sync.from_url(settings.redis_url, decode_responses=True)

    fired = 0
    with get_sync_db() as db:
        webhooks = db.execute(
            select(WebhookConfig).where(WebhookConfig.is_active.is_(True))
        ).scalars().all()

        if not webhooks:
            return {"fired": 0}

        nodes = db.execute(select(Node).where(Node.deleted_at.is_(None))).scalars().all()

        for node in nodes:
            node_payload = {
                "node_id": str(node.id),
                "hostname": node.hostname,
                "minion_id": node.minion_id,
                "ip_address": str(node.ip_address) if node.ip_address else None,
                "drift_score": node.drift_score,
                "status": node.status,
                "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
                "fired_at": datetime.now(UTC).isoformat(),
            }

            # Node offline alert
            if node.status == "offline":
                if not _dedup_key(r, "node.offline", str(node.id)):
                    for wh in webhooks:
                        if "node.offline" in wh.events or "*" in wh.events:
                            _fire_webhook(wh.url, {
                                "event": "node.offline",
                                "severity": "high",
                                **node_payload,
                            })
                            fired += 1

            # Critical drift alert
            if node.drift_score > _CRITICAL_DRIFT_THRESHOLD:
                if not _dedup_key(r, "drift.critical", str(node.id)):
                    for wh in webhooks:
                        if "drift.critical" in wh.events or "*" in wh.events:
                            _fire_webhook(wh.url, {
                                "event": "drift.critical",
                                "severity": "critical",
                                **node_payload,
                            })
                            fired += 1

    return {"fired": fired}
```

- [ ] **Step 4: Create webhooks API route**

```python
# fleet_platform/api/routes/webhooks.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.webhook import WebhookConfig

router = APIRouter(prefix="/api/v1/webhooks")

_VALID_EVENTS = {"node.offline", "drift.critical", "*"}


class WebhookCreate(BaseModel):
    name: str
    url: HttpUrl
    events: list[str] = ["*"]


class WebhookResponse(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    events: list
    is_active: bool


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    result = await db.execute(select(WebhookConfig))
    return [WebhookResponse(id=w.id, name=w.name, url=w.url, events=w.events, is_active=w.is_active)
            for w in result.scalars().all()]


@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    invalid = [e for e in payload.events if e not in _VALID_EVENTS]
    if invalid:
        raise HTTPException(status_code=422,
                            detail=f"Unknown events: {invalid}. Valid: {sorted(_VALID_EVENTS)}")
    wh = WebhookConfig(name=payload.name, url=str(payload.url), events=payload.events)
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    return WebhookResponse(id=wh.id, name=wh.name, url=wh.url, events=wh.events, is_active=wh.is_active)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    result = await db.execute(select(WebhookConfig).where(WebhookConfig.id == webhook_id))
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(wh)
    await db.commit()
```

- [ ] **Step 5: Add alert beat to celery_app.py**

```python
# In fleet_platform/workers/celery_app.py — add to includes and beat_schedule:
include=[
    "fleet_platform.workers.drift_tasks",
    "fleet_platform.workers.sbom_tasks",
    "fleet_platform.workers.maintenance",
    "fleet_platform.workers.alert_tasks",   # ← add
],

beat_schedule={
    "mark-stale-nodes": {...},
    "archive-old-sbom-scans": {...},
    "check-alerts": {
        "task": "fleet_platform.workers.alert_tasks.check_alerts",
        "schedule": 300,  # every 5 minutes
    },
},
```

- [ ] **Step 6: Write unit test**

```python
# tests/unit/test_alert_tasks.py
from unittest.mock import MagicMock, patch


def test_check_alerts_no_webhooks_returns_zero():
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("fleet_platform.workers.alert_tasks.get_sync_db", return_value=mock_db), \
         patch("fleet_platform.workers.alert_tasks._redis_sync") as mr:
        mr.from_url.return_value = MagicMock()
        from fleet_platform.workers.alert_tasks import check_alerts
        result = check_alerts()

    assert result["fired"] == 0
```

- [ ] **Step 7: Register webhooks router in main.py**

Add `webhooks` to imports and `app.include_router(webhooks.router, tags=["webhooks"])`.

- [ ] **Step 8: Run tests and full suite**

```bash
source .venv/bin/activate && pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add fleet_platform/db/migrations/versions/004_webhook_configs.py \
  fleet_platform/models/webhook.py fleet_platform/api/routes/webhooks.py \
  fleet_platform/workers/alert_tasks.py fleet_platform/workers/celery_app.py \
  fleet_platform/api/main.py tests/unit/test_alert_tasks.py
git commit -m "feat(M3): webhook alerting — node.offline + drift.critical events with dedup via Redis"
```

---

## Task 6: Final Build Verification

- [ ] **Step 1: Backend tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: `180+ passed, 0 failed`

- [ ] **Step 2: TypeScript + frontend build**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -3
```

Expected: zero errors, `✓ built`

---

## Self-Review

- [x] M10: Toast notifications — Task 1
- [x] M8: Execution target hostname — Task 2
- [x] Sidebar icon collapse — Task 3
- [x] Audit log frontend page — Task 4
- [x] M3: Webhook alerting (node.offline, drift.critical) — Task 5
