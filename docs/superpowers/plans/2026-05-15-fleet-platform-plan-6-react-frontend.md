# Fleet Platform Plan 6 — React Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade React 18 frontend that consumes the Fleet Platform REST API, providing fleet visibility, drift inspection, SBOM browsing, group management, and execution history.

**Architecture:** Single-page app in `frontend/` using Vite + React 18 + TypeScript + Tailwind. React Query owns all server state; Zustand owns UI-only state (auth, filters, sidebar). All pages are behind an AuthGuard that redirects to `/login` when no JWT is present. Vite's dev proxy forwards `/api` and `/auth` to the FastAPI backend at `localhost:8000`.

**Tech Stack:** React 18, TypeScript 5, Vite 5, Tailwind CSS 3, TanStack Query 5, TanStack Table 8, TanStack Virtual 3, Zustand 4, React Router 6, Recharts 2, date-fns 3.

---

## Backend API Reference (exact paths)

| Method | Path | Returns |
|--------|------|---------|
| POST | `/auth/login` | `{access_token, refresh_token, token_type}` |
| POST | `/auth/refresh` | `{access_token}` |
| GET | `/auth/me` | `{id, email, role}` |
| GET | `/api/v1/fleet/overview` | FleetOverview object |
| GET | `/api/v1/nodes?page&per_page&status&sort` | `{items, total, page, per_page}` |
| GET | `/api/v1/nodes/:id` | NodeDetail object |
| POST | `/api/v1/nodes/:id/tags` | `{key, value}` tag |
| DELETE | `/api/v1/nodes/:id/tags/:key` | 204 |
| GET | `/api/v1/drift?severity&page&per_page` | `{items: DriftSummary[], ...}` |
| GET | `/api/v1/drift/:nodeId/latest` | DriftRecord object |
| GET | `/api/v1/drift/:nodeId/history?page&per_page` | `{items: DriftSummary[], ...}` |
| POST | `/api/v1/drift/:nodeId/compute` | 202 `{status: "queued"}` |
| GET | `/api/v1/sbom/:nodeId/latest` | SBOMScan object |
| GET | `/api/v1/sbom/:nodeId/scans/:scanId/components?page&per_page` | `{items: SBOMComponent[], ...}` |
| GET | `/api/v1/sbom/search?q=` | `SBOMSearchResult[]` |
| GET | `/api/v1/groups?page&per_page` | `{items: Group[], ...}` |
| POST | `/api/v1/groups` | Group object |
| GET | `/api/v1/groups/:id` | Group object |
| GET | `/api/v1/groups/:id/nodes?page&per_page` | `{items: Node[], ...}` |
| GET | `/api/v1/executions?status&page&per_page` | `{items: ExecutionJob[], ...}` |
| GET | `/api/v1/executions/:id` | ExecutionJob object |
| GET | `/api/v1/executions/:id/results?page&per_page` | `{items: ExecutionResult[], ...}` |
| GET | `/api/v1/search?q=` | `{items: SearchResult[], ...}` |

---

## File Structure

```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── types/index.ts              # all TS interfaces
    ├── api/
    │   ├── client.ts               # fetch wrapper + JWT refresh
    │   ├── auth.ts                 # login, refresh, me
    │   ├── fleet.ts                # overview, nodes list, node detail, tags
    │   ├── drift.ts                # drift list, latest, history, trigger
    │   ├── sbom.ts                 # latest scan, components, search
    │   ├── groups.ts               # CRUD + members
    │   ├── executions.ts           # list, detail, results
    │   └── search.ts               # global search
    ├── stores/
    │   ├── authStore.ts            # token + user, persisted
    │   └── filterStore.ts          # node/drift filters, sidebar open
    ├── components/
    │   ├── Layout/
    │   │   ├── Layout.tsx          # sidebar + topbar shell
    │   │   ├── Sidebar.tsx         # nav links
    │   │   └── TopBar.tsx          # global search + user menu
    │   ├── AuthGuard.tsx           # redirect to /login if no token
    │   ├── StatusBadge.tsx         # online/offline/stale/unknown pill
    │   ├── DriftBadge.tsx          # 0-100 score + severity colour
    │   ├── Skeleton.tsx            # loading rows placeholder
    │   ├── ErrorState.tsx          # error + retry button
    │   └── Pagination.tsx          # prev/next page bar
    └── pages/
        ├── LoginPage.tsx
        ├── FleetDashboard.tsx
        ├── NodeDetail.tsx
        ├── DriftExplorer.tsx
        ├── SBOMExplorer.tsx
        ├── GroupExplorer.tsx
        ├── GroupDetail.tsx
        ├── ExecutionHistory.tsx
        └── JobDetail.tsx
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx` (placeholder)

- [ ] **Step 1: Scaffold the project**

```bash
cd /home/dk/Documents/git/kri
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Install all dependencies**

```bash
npm install \
  @tanstack/react-query@5 \
  @tanstack/react-table@8 \
  @tanstack/react-virtual@3 \
  zustand \
  react-router-dom@6 \
  recharts \
  date-fns \
  clsx

npm install -D \
  tailwindcss@3 \
  postcss \
  autoprefixer \
  @types/react \
  @types/react-dom

npx tailwindcss init -p
```

- [ ] **Step 3: Configure Tailwind**

Replace `frontend/tailwind.config.js` with:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 4: Configure Vite proxy**

Replace `frontend/vite.config.ts` with:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 5: Add Tailwind directives to CSS**

Replace `frontend/src/index.css` with:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 6: Verify the dev server starts**

```bash
cd /home/dk/Documents/git/kri/frontend && npm run dev
```

Expected: `VITE v5.x ready in xxxms` and `Local: http://localhost:5173/`  
Open the URL in a browser — should show the default Vite+React page. Stop with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
cd /home/dk/Documents/git/kri
git checkout -b feat/plan-6-react-frontend
git add frontend/
git commit -m "feat: scaffold React + Vite + TypeScript + Tailwind frontend"
```

---

## Task 2: TypeScript Types + API Client

**Files:**
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/fleet.ts`
- Create: `frontend/src/api/drift.ts`
- Create: `frontend/src/api/sbom.ts`
- Create: `frontend/src/api/groups.ts`
- Create: `frontend/src/api/executions.ts`
- Create: `frontend/src/api/search.ts`
- Create: `frontend/src/stores/authStore.ts`
- Create: `frontend/src/stores/filterStore.ts`

- [ ] **Step 1: Write all TypeScript interfaces**

```typescript
// frontend/src/types/index.ts

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface User {
  id: string
  email: string
  role: 'admin' | 'operator' | 'viewer'
}

export interface Tag {
  key: string
  value: string
}

export interface Node {
  id: string
  minion_id: string
  hostname: string | null
  ip_address: string | null
  os_version: string | null
  hardware_model: string | null
  status: 'online' | 'offline' | 'stale' | 'unknown'
  drift_score: number
  last_seen_at: string | null
  tags: Tag[]
}

export interface NodeDetail extends Node {
  os_build: string | null
  cpu_cores: number | null
  ram_gb: number | null
  storage_gb: number | null
  first_seen_at: string
  created_at: string
}

export interface FleetOverview {
  total_nodes: number
  online: number
  stale: number
  offline: number
  unknown: number
  avg_drift_score: number
  nodes_clean: number
  nodes_low: number
  nodes_medium: number
  nodes_high: number
  nodes_critical: number
  last_updated: string
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface DriftSummary {
  node_id: string
  hostname: string | null
  drift_score: number
  severity: string
  computed_at: string | null
  baseline_name: string | null
}

export interface DriftRecord {
  node_id: string
  baseline_id: string | null
  baseline_name: string | null
  computed_at: string
  drift_score: number
  severity: string
  missing_packages: Array<{ name: string; required_version: string | null }>
  extra_packages: Array<{ name: string; installed_version: string }>
  version_mismatches: Array<{ name: string; expected: string; actual: string }>
  service_drift: Array<{ name: string; expected: string; actual: string }>
  config_drift: unknown[]
}

export interface SBOMScan {
  id: string
  node_id: string
  syft_version: string | null
  format: string
  scanned_at: string
  component_count: number | null
}

export interface SBOMComponent {
  id: number
  scan_id: string
  node_id: string
  name: string
  version: string | null
  purl: string | null
  component_type: string | null
  licenses: string[]
  cpes: string[]
}

export interface SBOMSearchResult {
  name: string
  version: string | null
  purl: string | null
  component_type: string | null
  hostname: string
  node_id: string
  scan_id: string
  scanned_at: string
}

export interface Group {
  id: string
  name: string
  description: string | null
  type: 'static' | 'dynamic'
  predicate: Record<string, unknown> | null
  member_count: number
  created_at: string
}

export interface ExecutionJob {
  id: string
  salt_jid: string | null
  type: string
  target_type: string
  target_id: string | null
  triggered_by: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
}

export interface ExecutionResult {
  id: string
  job_id: string
  node_id: string
  status: string
  exit_code: number | null
  stdout: string | null
  stderr: string | null
  completed_at: string
}

export interface SearchResult {
  id: string
  hostname: string | null
  minion_id: string
  status: string
}
```

- [ ] **Step 2: Write the API client with JWT auto-refresh**

```typescript
// frontend/src/api/client.ts

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function tryRefresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return false
  try {
    const res = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return false
    const data = await res.json()
    localStorage.setItem('access_token', data.access_token)
    return true
  } catch {
    return false
  }
}

async function request<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const token = localStorage.getItem('access_token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  const res = await fetch(path, { ...init, headers })

  if (res.status === 401 && retry) {
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(path, init, false)
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    window.location.href = '/login'
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }

  if (res.status === 204) return undefined as unknown as T
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: 'DELETE' }),
}
```

- [ ] **Step 3: Write the auth API module**

```typescript
// frontend/src/api/auth.ts
import { api } from './client'
import type { TokenResponse, User } from '../types'

export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { email, password }),
  me: () => api.get<User>('/auth/me'),
}
```

- [ ] **Step 4: Write the fleet API module**

```typescript
// frontend/src/api/fleet.ts
import { api } from './client'
import type { FleetOverview, Node, NodeDetail, Paginated, Tag } from '../types'

export const fleetApi = {
  overview: () => api.get<FleetOverview>('/api/v1/fleet/overview'),
  nodes: (params: { page?: number; per_page?: number; status?: string; sort?: string }) => {
    const q = new URLSearchParams()
    if (params.page) q.set('page', String(params.page))
    if (params.per_page) q.set('per_page', String(params.per_page))
    if (params.status) q.set('status', params.status)
    if (params.sort) q.set('sort', params.sort)
    return api.get<Paginated<Node>>(`/api/v1/nodes?${q}`)
  },
  node: (id: string) => api.get<NodeDetail>(`/api/v1/nodes/${id}`),
  addTag: (nodeId: string, key: string, value: string) =>
    api.post<Tag>(`/api/v1/nodes/${nodeId}/tags`, { key, value }),
  removeTag: (nodeId: string, key: string) =>
    api.delete(`/api/v1/nodes/${nodeId}/tags/${key}`),
}
```

- [ ] **Step 5: Write the drift API module**

```typescript
// frontend/src/api/drift.ts
import { api } from './client'
import type { DriftRecord, DriftSummary, Paginated } from '../types'

export const driftApi = {
  list: (params: { severity?: string; page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params.severity) q.set('severity', params.severity)
    if (params.page) q.set('page', String(params.page))
    if (params.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<DriftSummary>>(`/api/v1/drift?${q}`)
  },
  latest: (nodeId: string) => api.get<DriftRecord>(`/api/v1/drift/${nodeId}/latest`),
  history: (nodeId: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<DriftSummary>>(`/api/v1/drift/${nodeId}/history?${q}`)
  },
  compute: (nodeId: string) =>
    api.post<{ status: string }>(`/api/v1/drift/${nodeId}/compute`),
}
```

- [ ] **Step 6: Write the SBOM API module**

```typescript
// frontend/src/api/sbom.ts
import { api } from './client'
import type { Paginated, SBOMComponent, SBOMScan, SBOMSearchResult } from '../types'

export const sbomApi = {
  latestScan: (nodeId: string) => api.get<SBOMScan>(`/api/v1/sbom/${nodeId}/latest`),
  components: (nodeId: string, scanId: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<SBOMComponent>>(
      `/api/v1/sbom/${nodeId}/scans/${scanId}/components?${q}`
    )
  },
  search: (q: string) =>
    api.get<SBOMSearchResult[]>(`/api/v1/sbom/search?q=${encodeURIComponent(q)}`),
}
```

- [ ] **Step 7: Write the groups API module**

```typescript
// frontend/src/api/groups.ts
import { api } from './client'
import type { Group, Node, Paginated } from '../types'

export const groupsApi = {
  list: (params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<Group>>(`/api/v1/groups?${q}`)
  },
  get: (id: string) => api.get<Group>(`/api/v1/groups/${id}`),
  create: (payload: { name: string; description?: string; type: string; predicate?: unknown }) =>
    api.post<Group>('/api/v1/groups', payload),
  members: (id: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<Node>>(`/api/v1/groups/${id}/nodes?${q}`)
  },
}
```

- [ ] **Step 8: Write the executions API module**

```typescript
// frontend/src/api/executions.ts
import { api } from './client'
import type { ExecutionJob, ExecutionResult, Paginated } from '../types'

export const executionsApi = {
  list: (params?: { status?: string; page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<ExecutionJob>>(`/api/v1/executions?${q}`)
  },
  get: (id: string) => api.get<ExecutionJob>(`/api/v1/executions/${id}`),
  results: (id: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<ExecutionResult>>(`/api/v1/executions/${id}/results?${q}`)
  },
}
```

- [ ] **Step 9: Write the search API module**

```typescript
// frontend/src/api/search.ts
import { api } from './client'
import type { Paginated, SearchResult } from '../types'

export const searchApi = {
  search: (q: string) =>
    api.get<Paginated<SearchResult>>(`/api/v1/search?q=${encodeURIComponent(q)}`),
}
```

- [ ] **Step 10: Write the Zustand auth store**

```typescript
// frontend/src/stores/authStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'

interface AuthState {
  user: User | null
  setUser: (user: User) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      setUser: (user) => set({ user }),
      clearAuth: () => {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null })
      },
    }),
    { name: 'auth-store' }
  )
)
```

- [ ] **Step 11: Write the Zustand filter store**

```typescript
// frontend/src/stores/filterStore.ts
import { create } from 'zustand'

interface FilterState {
  sidebarOpen: boolean
  nodeStatus: string
  driftSeverity: string
  executionStatus: string
  setSidebarOpen: (open: boolean) => void
  setNodeStatus: (status: string) => void
  setDriftSeverity: (severity: string) => void
  setExecutionStatus: (status: string) => void
  resetFilters: () => void
}

export const useFilterStore = create<FilterState>()((set) => ({
  sidebarOpen: true,
  nodeStatus: '',
  driftSeverity: '',
  executionStatus: '',
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setNodeStatus: (nodeStatus) => set({ nodeStatus }),
  setDriftSeverity: (driftSeverity) => set({ driftSeverity }),
  setExecutionStatus: (executionStatus) => set({ executionStatus }),
  resetFilters: () => set({ nodeStatus: '', driftSeverity: '', executionStatus: '' }),
}))
```

- [ ] **Step 12: Verify TypeScript compiles**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 13: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/types frontend/src/api frontend/src/stores
git commit -m "feat: TypeScript types, API client with JWT refresh, Zustand stores"
```

---

## Task 3: Shared Components + Auth Guard + App Shell

**Files:**
- Create: `frontend/src/components/AuthGuard.tsx`
- Create: `frontend/src/components/StatusBadge.tsx`
- Create: `frontend/src/components/DriftBadge.tsx`
- Create: `frontend/src/components/Skeleton.tsx`
- Create: `frontend/src/components/ErrorState.tsx`
- Create: `frontend/src/components/Pagination.tsx`
- Create: `frontend/src/components/Layout/Sidebar.tsx`
- Create: `frontend/src/components/Layout/TopBar.tsx`
- Create: `frontend/src/components/Layout/Layout.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Write shared components**

```tsx
// frontend/src/components/StatusBadge.tsx
const colours: Record<string, string> = {
  online: 'bg-green-100 text-green-800',
  offline: 'bg-red-100 text-red-800',
  stale: 'bg-yellow-100 text-yellow-800',
  unknown: 'bg-gray-100 text-gray-600',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colours[status] ?? colours.unknown}`}>
      {status}
    </span>
  )
}
```

```tsx
// frontend/src/components/DriftBadge.tsx
function severityColour(score: number): string {
  if (score <= 5) return 'bg-green-100 text-green-800'
  if (score <= 20) return 'bg-blue-100 text-blue-800'
  if (score <= 50) return 'bg-yellow-100 text-yellow-800'
  if (score <= 80) return 'bg-orange-100 text-orange-800'
  return 'bg-red-100 text-red-800'
}

export function DriftBadge({ score }: { score: number }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium tabular-nums ${severityColour(score)}`}>
      {score}
    </span>
  )
}
```

```tsx
// frontend/src/components/Skeleton.tsx
export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 bg-gray-200 rounded animate-pulse" />
      ))}
    </div>
  )
}
```

```tsx
// frontend/src/components/ErrorState.tsx
export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <p className="text-red-600 font-medium">{message}</p>
      {retry && (
        <button
          onClick={retry}
          className="mt-4 px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700"
        >
          Retry
        </button>
      )}
    </div>
  )
}
```

```tsx
// frontend/src/components/Pagination.tsx
interface PaginationProps {
  page: number
  total: number
  perPage: number
  onPage: (page: number) => void
}

export function Pagination({ page, total, perPage, onPage }: PaginationProps) {
  const totalPages = Math.ceil(total / perPage)
  if (totalPages <= 1) return null
  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 text-sm text-gray-600">
      <span>{total} total</span>
      <div className="flex gap-2">
        <button
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          className="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50"
        >
          Previous
        </button>
        <span className="px-3 py-1">
          {page} / {totalPages}
        </span>
        <button
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
          className="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50"
        >
          Next
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Write AuthGuard**

```tsx
// frontend/src/components/AuthGuard.tsx
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('access_token')
  const user = useAuthStore((s) => s.user)
  if (!token || !user) return <Navigate to="/login" replace />
  return <>{children}</>
}
```

- [ ] **Step 3: Write Sidebar**

```tsx
// frontend/src/components/Layout/Sidebar.tsx
import { NavLink } from 'react-router-dom'
import { useFilterStore } from '../../stores/filterStore'

const links = [
  { to: '/fleet', label: 'Fleet' },
  { to: '/drift', label: 'Drift' },
  { to: '/sbom', label: 'SBOM' },
  { to: '/groups', label: 'Groups' },
  { to: '/executions', label: 'Executions' },
]

export function Sidebar() {
  const open = useFilterStore((s) => s.sidebarOpen)
  if (!open) return null
  return (
    <nav className="w-56 flex-shrink-0 bg-gray-900 text-gray-100 min-h-screen flex flex-col">
      <div className="px-4 py-5 text-lg font-bold tracking-tight text-white border-b border-gray-700">
        Fleet Platform
      </div>
      <ul className="flex-1 py-4 space-y-1">
        {links.map(({ to, label }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) =>
                `block px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
```

- [ ] **Step 4: Write TopBar**

```tsx
// frontend/src/components/Layout/TopBar.tsx
import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { searchApi } from '../../api/search'
import { useAuthStore } from '../../stores/authStore'
import { useFilterStore } from '../../stores/filterStore'

export function TopBar() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const navigate = useNavigate()
  const { clearAuth, user } = useAuthStore()
  const toggleSidebar = useFilterStore((s) => s.setSidebarOpen)
  const sidebarOpen = useFilterStore((s) => s.sidebarOpen)

  const { data } = useQuery({
    queryKey: ['search', q],
    queryFn: () => searchApi.search(q),
    enabled: q.length >= 3,
    staleTime: 5_000,
  })

  function handleInput(value: string) {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setQ(value), 300)
    setOpen(value.length >= 3)
  }

  function handleLogout() {
    clearAuth()
    navigate('/login')
  }

  return (
    <header className="h-14 flex items-center px-4 bg-white border-b border-gray-200 gap-4">
      <button
        onClick={() => toggleSidebar(!sidebarOpen)}
        className="text-gray-500 hover:text-gray-700"
        aria-label="Toggle sidebar"
      >
        ☰
      </button>
      <div className="relative flex-1 max-w-md">
        <input
          type="search"
          placeholder="Search nodes… (min 3 chars)"
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => q.length >= 3 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
        {open && data && data.items.length > 0 && (
          <ul className="absolute top-full mt-1 w-full bg-white border border-gray-200 rounded shadow-lg z-50 max-h-60 overflow-auto">
            {data.items.map((r) => (
              <li key={r.id}>
                <button
                  className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50"
                  onClick={() => { navigate(`/nodes/${r.id}`); setOpen(false) }}
                >
                  <span className="font-medium">{r.hostname ?? r.minion_id}</span>
                  <span className="ml-2 text-gray-400 text-xs">{r.status}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="ml-auto flex items-center gap-3 text-sm text-gray-600">
        <span>{user?.email}</span>
        <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">{user?.role}</span>
        <button onClick={handleLogout} className="text-red-500 hover:text-red-700">
          Logout
        </button>
      </div>
    </header>
  )
}
```

- [ ] **Step 5: Write Layout**

```tsx
// frontend/src/components/Layout/Layout.tsx
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

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
    </div>
  )
}
```

- [ ] **Step 6: Write LoginPage**

```tsx
// frontend/src/pages/LoginPage.tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const tokens = await authApi.login(email, password)
      localStorage.setItem('access_token', tokens.access_token)
      localStorage.setItem('refresh_token', tokens.refresh_token)
      const user = await authApi.me()
      setUser(user)
      navigate('/fleet')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm bg-white rounded-lg shadow p-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Fleet Platform</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-brand-600 text-white rounded font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 7: Wire up App.tsx with routing**

```tsx
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthGuard } from './components/AuthGuard'
import { Layout } from './components/Layout/Layout'
import { LoginPage } from './pages/LoginPage'
import { FleetDashboard } from './pages/FleetDashboard'
import { NodeDetail } from './pages/NodeDetail'
import { DriftExplorer } from './pages/DriftExplorer'
import { SBOMExplorer } from './pages/SBOMExplorer'
import { GroupExplorer } from './pages/GroupExplorer'
import { GroupDetail } from './pages/GroupDetail'
import { ExecutionHistory } from './pages/ExecutionHistory'
import { JobDetail } from './pages/JobDetail'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <AuthGuard>
                <Layout />
              </AuthGuard>
            }
          >
            <Route index element={<Navigate to="/fleet" replace />} />
            <Route path="/fleet" element={<FleetDashboard />} />
            <Route path="/nodes/:nodeId" element={<NodeDetail />} />
            <Route path="/drift" element={<DriftExplorer />} />
            <Route path="/sbom" element={<SBOMExplorer />} />
            <Route path="/groups" element={<GroupExplorer />} />
            <Route path="/groups/:groupId" element={<GroupDetail />} />
            <Route path="/executions" element={<ExecutionHistory />} />
            <Route path="/executions/:jobId" element={<JobDetail />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

- [ ] **Step 8: Add placeholder pages so App.tsx compiles**

Create stub exports for pages not yet implemented (Tasks 4–9 will replace these):

```tsx
// frontend/src/pages/FleetDashboard.tsx
export function FleetDashboard() { return <div>Fleet Dashboard — coming soon</div> }
```
```tsx
// frontend/src/pages/NodeDetail.tsx
export function NodeDetail() { return <div>Node Detail — coming soon</div> }
```
```tsx
// frontend/src/pages/DriftExplorer.tsx
export function DriftExplorer() { return <div>Drift Explorer — coming soon</div> }
```
```tsx
// frontend/src/pages/SBOMExplorer.tsx
export function SBOMExplorer() { return <div>SBOM Explorer — coming soon</div> }
```
```tsx
// frontend/src/pages/GroupExplorer.tsx
export function GroupExplorer() { return <div>Group Explorer — coming soon</div> }
```
```tsx
// frontend/src/pages/GroupDetail.tsx
export function GroupDetail() { return <div>Group Detail — coming soon</div> }
```
```tsx
// frontend/src/pages/ExecutionHistory.tsx
export function ExecutionHistory() { return <div>Execution History — coming soon</div> }
```
```tsx
// frontend/src/pages/JobDetail.tsx
export function JobDetail() { return <div>Job Detail — coming soon</div> }
```

- [ ] **Step 9: Update main.tsx**

```tsx
// frontend/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App.tsx'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 10: Verify it compiles and runs**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit && npm run dev &
sleep 3
curl -s http://localhost:5173/ | grep -q 'Fleet Platform\|<!doctype html' && echo "OK"
pkill -f "vite" 2>/dev/null
```

Expected: `OK`

- [ ] **Step 11: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/
git commit -m "feat: shared components, AuthGuard, Layout, LoginPage, routing shell"
```

---

## Task 4: Fleet Dashboard

**Files:**
- Modify: `frontend/src/pages/FleetDashboard.tsx` (replace stub)

- [ ] **Step 1: Implement FleetDashboard**

```tsx
// frontend/src/pages/FleetDashboard.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'

export function FleetDashboard() {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')

  const { data: overview, isLoading: ovLoading } = useQuery({
    queryKey: ['fleet-overview'],
    queryFn: fleetApi.overview,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  const {
    data: nodes,
    isLoading: nodesLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['nodes', page, statusFilter],
    queryFn: () => fleetApi.nodes({ page, per_page: 50, status: statusFilter || undefined }),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>

      {/* Stats bar */}
      {ovLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : overview ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Nodes', value: overview.total_nodes, colour: 'text-gray-900' },
            { label: 'Online', value: overview.online, colour: 'text-green-600' },
            { label: 'Offline / Stale', value: overview.offline + overview.stale, colour: 'text-red-600' },
            { label: 'Avg Drift Score', value: overview.avg_drift_score, colour: 'text-brand-600' },
          ].map(({ label, value, colour }) => (
            <div key={label} className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
              <p className={`text-3xl font-bold mt-1 ${colour}`}>{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      {/* Filters */}
      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Status:</label>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1"
        >
          <option value="">All</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="stale">Stale</option>
          <option value="unknown">Unknown</option>
        </select>
      </div>

      {/* Node table */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {nodesLoading ? (
          <Skeleton rows={10} />
        ) : isError ? (
          <ErrorState message="Failed to load nodes" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">OS</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">Last Seen</th>
                  <th className="px-4 py-3">Tags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {nodes?.items.map((node) => (
                  <tr key={node.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-medium">
                      <Link to={`/nodes/${node.id}`} className="text-brand-600 hover:underline">
                        {node.hostname ?? node.minion_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={node.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-600">{node.os_version ?? '—'}</td>
                    <td className="px-4 py-3">
                      <DriftBadge score={node.drift_score} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {node.last_seen_at
                        ? formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {node.tags.map((t) => (
                          <span
                            key={t.key}
                            className="text-xs bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded"
                          >
                            {t.key}={t.value}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {nodes && (
              <Pagination
                page={page}
                total={nodes.total}
                perPage={nodes.per_page}
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

- [ ] **Step 2: Start dev server and verify Fleet Dashboard**

Make sure the FastAPI backend is running first:
```bash
source /home/dk/Documents/git/kri/.venv/bin/activate && uvicorn fleet_platform.api.main:app --port 8000 &
sleep 2
```

Then start the frontend:
```bash
cd /home/dk/Documents/git/kri/frontend && npm run dev
```

Log in at `http://localhost:5173/login` with `admin@fleet.local` / `changeme`. Verify:
- Stats bar shows 4 cards
- Node table loads with hostname, status, drift score, last seen
- Status filter dropdown works
- Clicking a node navigates to `/nodes/:id` (shows placeholder)
- Logout works

Stop servers: `pkill -f uvicorn; pkill -f vite`

- [ ] **Step 3: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/FleetDashboard.tsx
git commit -m "feat: Fleet Dashboard — stats bar + paginated node table"
```

---

## Task 5: Node Detail Page

**Files:**
- Modify: `frontend/src/pages/NodeDetail.tsx` (replace stub)

- [ ] **Step 1: Implement NodeDetail with all tabs**

```tsx
// frontend/src/pages/NodeDetail.tsx
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { driftApi } from '../api/drift'
import { sbomApi } from '../api/sbom'
import { executionsApi } from '../api/executions'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow, format } from 'date-fns'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useState as useInputState } from 'react'

type Tab = 'overview' | 'drift' | 'sbom' | 'executions'

export function NodeDetail() {
  const { nodeId } = useParams<{ nodeId: string }>()
  const [tab, setTab] = useState<Tab>('overview')
  const [execPage, setExecPage] = useState(1)
  const [compPage, setCompPage] = useState(1)
  const [tagKey, setTagKey] = useInputState('')
  const [tagValue, setTagValue] = useInputState('')
  const qc = useQueryClient()

  const { data: node, isLoading, isError, refetch } = useQuery({
    queryKey: ['node', nodeId],
    queryFn: () => fleetApi.node(nodeId!),
    staleTime: 60_000,
    enabled: !!nodeId,
  })

  const { data: latestDrift } = useQuery({
    queryKey: ['drift-latest', nodeId],
    queryFn: () => driftApi.latest(nodeId!),
    staleTime: 60_000,
    enabled: !!nodeId && tab === 'drift',
  })

  const { data: driftHistory } = useQuery({
    queryKey: ['drift-history', nodeId],
    queryFn: () => driftApi.history(nodeId!, { per_page: 30 }),
    staleTime: 60_000,
    enabled: !!nodeId && tab === 'drift',
  })

  const { data: sbomScan } = useQuery({
    queryKey: ['sbom-latest', nodeId],
    queryFn: () => sbomApi.latestScan(nodeId!),
    staleTime: 300_000,
    enabled: !!nodeId && tab === 'sbom',
  })

  const { data: components } = useQuery({
    queryKey: ['sbom-components', nodeId, sbomScan?.id, compPage],
    queryFn: () => sbomApi.components(nodeId!, sbomScan!.id, { page: compPage, per_page: 100 }),
    staleTime: 300_000,
    enabled: !!sbomScan?.id,
  })

  const { data: executions } = useQuery({
    queryKey: ['executions', nodeId, execPage],
    queryFn: () => executionsApi.list({ page: execPage, per_page: 25 }),
    staleTime: 10_000,
    enabled: !!nodeId && tab === 'executions',
  })

  const addTagMutation = useMutation({
    mutationFn: () => fleetApi.addTag(nodeId!, tagKey, tagValue),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      setTagKey('')
      setTagValue('')
    },
  })

  const removeTagMutation = useMutation({
    mutationFn: (key: string) => fleetApi.removeTag(nodeId!, key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['node', nodeId] }),
  })

  const computeMutation = useMutation({
    mutationFn: () => driftApi.compute(nodeId!),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['drift-latest', nodeId] }), 3000)
    },
  })

  if (isLoading) return <Skeleton rows={8} />
  if (isError || !node) return <ErrorState message="Node not found" retry={refetch} />

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'drift', label: 'Drift' },
    { id: 'sbom', label: 'SBOM' },
    { id: 'executions', label: 'Executions' },
  ]

  const chartData = driftHistory?.items
    .slice()
    .reverse()
    .map((d) => ({
      date: format(new Date(d.computed_at ?? ''), 'MM/dd'),
      score: d.drift_score,
    }))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">
              {node.hostname ?? node.minion_id}
            </h1>
            <StatusBadge status={node.status} />
            <DriftBadge score={node.drift_score} />
          </div>
          <p className="text-sm text-gray-500 mt-1">
            {node.ip_address ?? 'IP unknown'} ·{' '}
            {node.last_seen_at
              ? `Last seen ${formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })}`
              : 'Never seen'}
          </p>
        </div>
        <Link to="/fleet" className="text-sm text-brand-600 hover:underline">
          ← Fleet
        </Link>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 flex gap-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
            <h3 className="font-semibold text-gray-700">Hardware</h3>
            <dl className="space-y-1 text-sm">
              {[
                ['Model', node.hardware_model],
                ['CPU Cores', node.cpu_cores],
                ['RAM', node.ram_gb ? `${node.ram_gb} GB` : null],
                ['Storage', node.storage_gb ? `${node.storage_gb} GB` : null],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="font-medium">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
            <h3 className="font-semibold text-gray-700">OS</h3>
            <dl className="space-y-1 text-sm">
              {[
                ['Version', node.os_version],
                ['Build', node.os_build],
                ['First Seen', node.first_seen_at ? format(new Date(node.first_seen_at), 'PP') : null],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="font-medium">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2">
            <h3 className="font-semibold text-gray-700 mb-3">Tags</h3>
            <div className="flex flex-wrap gap-2 mb-3">
              {node.tags.map((t) => (
                <span
                  key={t.key}
                  className="flex items-center gap-1 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded"
                >
                  {t.key}={t.value}
                  <button
                    onClick={() => removeTagMutation.mutate(t.key)}
                    className="ml-1 text-gray-400 hover:text-red-500"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <form
              onSubmit={(e) => { e.preventDefault(); addTagMutation.mutate() }}
              className="flex gap-2"
            >
              <input
                placeholder="key"
                value={tagKey}
                onChange={(e) => setTagKey(e.target.value)}
                required
                className="w-28 text-sm border border-gray-300 rounded px-2 py-1"
              />
              <input
                placeholder="value"
                value={tagValue}
                onChange={(e) => setTagValue(e.target.value)}
                required
                className="w-28 text-sm border border-gray-300 rounded px-2 py-1"
              />
              <button
                type="submit"
                disabled={addTagMutation.isPending}
                className="px-3 py-1 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50"
              >
                Add Tag
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Drift Tab */}
      {tab === 'drift' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button
              onClick={() => computeMutation.mutate()}
              disabled={computeMutation.isPending}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50"
            >
              {computeMutation.isPending ? 'Queuing…' : 'Trigger Drift Compute'}
            </button>
          </div>
          {latestDrift && (
            <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
              <div className="flex items-center gap-4">
                <div>
                  <p className="text-xs text-gray-500 uppercase">Drift Score</p>
                  <p className="text-3xl font-bold text-gray-900">{latestDrift.drift_score}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase">Severity</p>
                  <p className="text-lg font-semibold capitalize">{latestDrift.severity}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase">Baseline</p>
                  <p className="text-sm">{latestDrift.baseline_name ?? '—'}</p>
                </div>
              </div>
              {[
                { title: 'Missing Packages', items: latestDrift.missing_packages, key: 'name' },
                { title: 'Extra Packages', items: latestDrift.extra_packages, key: 'name' },
                { title: 'Version Mismatches', items: latestDrift.version_mismatches, key: 'name' },
              ].map(({ title, items, key }) =>
                items.length > 0 ? (
                  <div key={title}>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">{title}</h4>
                    <ul className="text-sm bg-gray-50 rounded p-3 space-y-1">
                      {items.map((item, i) => (
                        <li key={i} className="font-mono text-gray-700">
                          {JSON.stringify(item)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null
              )}
            </div>
          )}
          {chartData && chartData.length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h4 className="text-sm font-medium text-gray-700 mb-3">Drift History (30 days)</h4>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={chartData}>
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="score" stroke="#2563eb" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* SBOM Tab */}
      {tab === 'sbom' && (
        <div className="space-y-4">
          {sbomScan ? (
            <>
              <div className="bg-white rounded-lg border border-gray-200 p-4 flex gap-8 text-sm">
                <div>
                  <p className="text-gray-500">Scanned</p>
                  <p className="font-medium">
                    {format(new Date(sbomScan.scanned_at), 'PPpp')}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500">Syft</p>
                  <p className="font-medium">{sbomScan.syft_version ?? '—'}</p>
                </div>
                <div>
                  <p className="text-gray-500">Components</p>
                  <p className="font-medium">{sbomScan.component_count ?? '—'}</p>
                </div>
              </div>
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Licenses</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {components?.items.map((c) => (
                      <tr key={c.id} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-mono text-xs">{c.name}</td>
                        <td className="px-4 py-2 text-gray-600">{c.version ?? '—'}</td>
                        <td className="px-4 py-2 text-gray-600">{c.component_type ?? '—'}</td>
                        <td className="px-4 py-2 text-gray-600">{c.licenses.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {components && (
                  <Pagination
                    page={compPage}
                    total={components.total}
                    perPage={components.per_page}
                    onPage={setCompPage}
                  />
                )}
              </div>
            </>
          ) : (
            <p className="text-gray-500 text-sm">No SBOM scans yet for this node.</p>
          )}
        </div>
      )}

      {/* Executions Tab */}
      {tab === 'executions' && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Triggered By</th>
                <th className="px-4 py-3">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {executions?.items.map((j) => (
                <tr key={j.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link to={`/executions/${j.id}`} className="text-brand-600 hover:underline">
                      {j.type}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        j.status === 'completed'
                          ? 'bg-green-100 text-green-800'
                          : j.status === 'failed'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}
                    >
                      {j.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-600">{j.triggered_by}</td>
                  <td className="px-4 py-2 text-gray-500">
                    {j.started_at
                      ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true })
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {executions && (
            <Pagination
              page={execPage}
              total={executions.total}
              perPage={executions.per_page}
              onPage={setExecPage}
            />
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify NodeDetail**

Start servers and navigate to a node detail page. Verify:
- Header shows hostname, status badge, drift badge
- Overview tab: hardware card, OS card, tags with add/remove
- Drift tab: score, severity, missing/extra packages, compute button, line chart
- SBOM tab: scan metadata + component table
- Executions tab: job list

- [ ] **Step 3: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/NodeDetail.tsx
git commit -m "feat: Node Detail page — Overview, Drift, SBOM, Executions tabs"
```

---

## Task 6: Drift Explorer

**Files:**
- Modify: `frontend/src/pages/DriftExplorer.tsx` (replace stub)

- [ ] **Step 1: Implement DriftExplorer**

```tsx
// frontend/src/pages/DriftExplorer.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { driftApi } from '../api/drift'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'
import { useFilterStore } from '../stores/filterStore'

const SEVERITIES = ['', 'clean', 'low', 'medium', 'high', 'critical']

export function DriftExplorer() {
  const [page, setPage] = useState(1)
  const { driftSeverity, setDriftSeverity } = useFilterStore()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['drift', driftSeverity, page],
    queryFn: () => driftApi.list({ severity: driftSeverity || undefined, page, per_page: 50 }),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Drift Explorer</h1>

      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Severity:</label>
        <select
          value={driftSeverity}
          onChange={(e) => { setDriftSeverity(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1"
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s || 'All'}</option>
          ))}
        </select>
        {data && (
          <span className="text-sm text-gray-500">{data.total} nodes</span>
        )}
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={10} />
        ) : isError ? (
          <ErrorState message="Failed to load drift data" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Drift Score</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Baseline</th>
                  <th className="px-4 py-3">Computed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((d) => (
                  <tr key={d.node_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">
                      <Link to={`/nodes/${d.node_id}`} className="text-brand-600 hover:underline">
                        {d.hostname ?? d.node_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <DriftBadge score={d.drift_score} />
                    </td>
                    <td className="px-4 py-3 capitalize text-gray-600">{d.severity}</td>
                    <td className="px-4 py-3 text-gray-600">{d.baseline_name ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {d.computed_at
                        ? formatDistanceToNow(new Date(d.computed_at), { addSuffix: true })
                        : '—'}
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

- [ ] **Step 2: Verify DriftExplorer**

Navigate to `/drift`. Verify severity filter works, nodes are listed with drift badges, clicking hostname navigates to node detail.

- [ ] **Step 3: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/DriftExplorer.tsx
git commit -m "feat: Drift Explorer — severity filter, ranked node table"
```

---

## Task 7: SBOM Explorer

**Files:**
- Modify: `frontend/src/pages/SBOMExplorer.tsx` (replace stub)

- [ ] **Step 1: Implement SBOMExplorer**

```tsx
// frontend/src/pages/SBOMExplorer.tsx
import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { sbomApi } from '../api/sbom'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { formatDistanceToNow } from 'date-fns'

export function SBOMExplorer() {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  function handleInput(value: string) {
    setQ(value)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQ(value), 300)
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['sbom-search', debouncedQ],
    queryFn: () => sbomApi.search(debouncedQ),
    enabled: debouncedQ.length >= 3,
    staleTime: 60_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">SBOM Explorer</h1>

      <div className="max-w-lg">
        <input
          type="search"
          placeholder="Search packages fleet-wide (min 3 chars)…"
          value={q}
          onChange={(e) => handleInput(e.target.value)}
          className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
        {q.length > 0 && q.length < 3 && (
          <p className="mt-1 text-xs text-gray-500">Type at least 3 characters to search</p>
        )}
      </div>

      {debouncedQ.length >= 3 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          {isLoading ? (
            <Skeleton rows={8} />
          ) : isError ? (
            <ErrorState message="Search failed" retry={refetch} />
          ) : data && data.length === 0 ? (
            <p className="p-8 text-center text-gray-500 text-sm">
              No packages found matching "{debouncedQ}"
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Package</th>
                  <th className="px-4 py-3">Version</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Node</th>
                  <th className="px-4 py-3">Scanned</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.map((r, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs font-medium">{r.name}</td>
                    <td className="px-4 py-3 text-gray-600">{r.version ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-600">{r.component_type ?? '—'}</td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/nodes/${r.node_id}`}
                        className="text-brand-600 hover:underline"
                      >
                        {r.hostname}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {formatDistanceToNow(new Date(r.scanned_at), { addSuffix: true })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify SBOMExplorer**

Navigate to `/sbom`. Type a package name (e.g. "openssl"). Verify results show with node links. Verify < 3 chars shows a hint message.

- [ ] **Step 3: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/SBOMExplorer.tsx
git commit -m "feat: SBOM Explorer — debounced fleet-wide package search"
```

---

## Task 8: Groups Pages

**Files:**
- Modify: `frontend/src/pages/GroupExplorer.tsx` (replace stub)
- Modify: `frontend/src/pages/GroupDetail.tsx` (replace stub)

- [ ] **Step 1: Implement GroupExplorer**

```tsx
// frontend/src/pages/GroupExplorer.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { groupsApi } from '../api/groups'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { format } from 'date-fns'

export function GroupExplorer() {
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState<'static' | 'dynamic'>('static')
  const [predicate, setPredicate] = useState('{"and": []}')
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['groups', page],
    queryFn: () => groupsApi.list({ page, per_page: 25 }),
    staleTime: 30_000,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      groupsApi.create({
        name,
        description: description || undefined,
        type,
        predicate: type === 'dynamic' ? JSON.parse(predicate) : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['groups'] })
      setShowForm(false)
      setName('')
      setDescription('')
      setPredicate('{"and": []}')
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Groups</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700"
        >
          {showForm ? 'Cancel' : 'New Group'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={(e) => { e.preventDefault(); createMutation.mutate() }}
          className="bg-white rounded-lg border border-gray-200 p-4 space-y-4"
        >
          <h3 className="font-medium text-gray-700">Create Group</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Name</label>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Type</label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value as 'static' | 'dynamic')}
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5"
              >
                <option value="static">Static</option>
                <option value="dynamic">Dynamic</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full text-sm border border-gray-300 rounded px-2 py-1.5"
            />
          </div>
          {type === 'dynamic' && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Predicate (JSON) — e.g. {`{"and":[{"key":"env","value":"prod"}]}`}
              </label>
              <textarea
                value={predicate}
                onChange={(e) => setPredicate(e.target.value)}
                rows={3}
                className="w-full text-sm font-mono border border-gray-300 rounded px-2 py-1.5"
              />
            </div>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50"
            >
              {createMutation.isPending ? 'Creating…' : 'Create'}
            </button>
            {createMutation.isError && (
              <p className="text-red-600 text-sm self-center">
                {(createMutation.error as Error).message}
              </p>
            )}
          </div>
        </form>
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={6} />
        ) : isError ? (
          <ErrorState message="Failed to load groups" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Members</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((g) => (
                  <tr key={g.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link to={`/groups/${g.id}`} className="text-brand-600 hover:underline font-medium">
                        {g.name}
                      </Link>
                      {g.description && (
                        <p className="text-xs text-gray-400">{g.description}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${g.type === 'dynamic' ? 'bg-purple-100 text-purple-800' : 'bg-gray-100 text-gray-700'}`}>
                        {g.type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{g.member_count}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {format(new Date(g.created_at), 'PP')}
                    </td>
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

- [ ] **Step 2: Implement GroupDetail**

```tsx
// frontend/src/pages/GroupDetail.tsx
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { groupsApi } from '../api/groups'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'

export function GroupDetail() {
  const { groupId } = useParams<{ groupId: string }>()
  const [page, setPage] = useState(1)

  const { data: group, isLoading: gLoading, isError: gError } = useQuery({
    queryKey: ['group', groupId],
    queryFn: () => groupsApi.get(groupId!),
    enabled: !!groupId,
  })

  const { data: members, isLoading: mLoading } = useQuery({
    queryKey: ['group-members', groupId, page],
    queryFn: () => groupsApi.members(groupId!, { page, per_page: 25 }),
    enabled: !!groupId,
    staleTime: 30_000,
  })

  if (gLoading) return <Skeleton rows={4} />
  if (gError || !group) return <ErrorState message="Group not found" />

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/groups" className="text-sm text-brand-600 hover:underline">← Groups</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{group.name}</h1>
        <span className={`text-xs px-2 py-0.5 rounded ${group.type === 'dynamic' ? 'bg-purple-100 text-purple-800' : 'bg-gray-100 text-gray-700'}`}>
          {group.type}
        </span>
      </div>

      {group.description && (
        <p className="text-gray-600">{group.description}</p>
      )}

      {group.predicate && (
        <div className="bg-gray-50 rounded p-3">
          <p className="text-xs text-gray-500 mb-1 uppercase">Predicate</p>
          <pre className="text-xs font-mono text-gray-700">{JSON.stringify(group.predicate, null, 2)}</pre>
        </div>
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 text-sm font-medium text-gray-700">
          Members ({group.member_count})
        </div>
        {mLoading ? (
          <Skeleton rows={5} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">OS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {members?.items.map((n) => (
                  <tr key={n.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link to={`/nodes/${n.id}`} className="text-brand-600 hover:underline font-medium">
                        {n.hostname ?? n.minion_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={n.status} /></td>
                    <td className="px-4 py-3"><DriftBadge score={n.drift_score} /></td>
                    <td className="px-4 py-3 text-gray-600">{n.os_version ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {members && (
              <Pagination page={page} total={members.total} perPage={members.per_page} onPage={setPage} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify Groups**

Navigate to `/groups`. Verify: group list loads, create form works (try creating a static group), clicking a group shows its detail with member nodes.

- [ ] **Step 4: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/GroupExplorer.tsx frontend/src/pages/GroupDetail.tsx
git commit -m "feat: Group Explorer + Group Detail pages"
```

---

## Task 9: Execution History Pages

**Files:**
- Modify: `frontend/src/pages/ExecutionHistory.tsx` (replace stub)
- Modify: `frontend/src/pages/JobDetail.tsx` (replace stub)

- [ ] **Step 1: Implement ExecutionHistory**

```tsx
// frontend/src/pages/ExecutionHistory.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { executionsApi } from '../api/executions'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow, formatDuration, intervalToDuration } from 'date-fns'
import { useFilterStore } from '../stores/filterStore'

const STATUSES = ['', 'pending', 'running', 'completed', 'failed']

function jobDuration(job: { started_at: string | null; completed_at: string | null }): string {
  if (!job.started_at || !job.completed_at) return '—'
  const duration = intervalToDuration({
    start: new Date(job.started_at),
    end: new Date(job.completed_at),
  })
  return formatDuration(duration, { format: ['minutes', 'seconds'] }) || '<1s'
}

export function ExecutionHistory() {
  const [page, setPage] = useState(1)
  const { executionStatus, setExecutionStatus } = useFilterStore()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['executions', executionStatus, page],
    queryFn: () => executionsApi.list({ status: executionStatus || undefined, page, per_page: 25 }),
    staleTime: 10_000,
    refetchInterval: 15_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Execution History</h1>

      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Status:</label>
        <select
          value={executionStatus}
          onChange={(e) => { setExecutionStatus(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s || 'All'}</option>
          ))}
        </select>
        {data && <span className="text-sm text-gray-500">{data.total} jobs</span>}
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={8} />
        ) : isError ? (
          <ErrorState message="Failed to load executions" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Target</th>
                  <th className="px-4 py-3">Triggered By</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((j) => (
                  <tr key={j.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link to={`/executions/${j.id}`} className="text-brand-600 hover:underline font-mono text-xs">
                        {j.type}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        j.status === 'completed' ? 'bg-green-100 text-green-800' :
                        j.status === 'failed' ? 'bg-red-100 text-red-800' :
                        j.status === 'running' ? 'bg-blue-100 text-blue-800' :
                        'bg-gray-100 text-gray-700'
                      }`}>
                        {j.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs font-mono">
                      {j.target_type}{j.target_id ? `:${j.target_id.slice(0, 8)}` : ''}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{j.triggered_by}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {j.started_at
                        ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true })
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">{jobDuration(j)}</td>
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

- [ ] **Step 2: Implement JobDetail**

```tsx
// frontend/src/pages/JobDetail.tsx
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { executionsApi } from '../api/executions'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { format } from 'date-fns'

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()

  const { data: job, isLoading: jLoading, isError: jError } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => executionsApi.get(jobId!),
    enabled: !!jobId,
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 5_000 : false,
  })

  const { data: results, isLoading: rLoading } = useQuery({
    queryKey: ['job-results', jobId],
    queryFn: () => executionsApi.results(jobId!, { per_page: 100 }),
    enabled: !!jobId && job?.status !== 'pending',
    staleTime: 10_000,
  })

  if (jLoading) return <Skeleton rows={4} />
  if (jError || !job) return <ErrorState message="Job not found" />

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/executions" className="text-sm text-brand-600 hover:underline">← Executions</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900 font-mono">{job.type}</h1>
        <span className={`text-xs px-2 py-0.5 rounded ${
          job.status === 'completed' ? 'bg-green-100 text-green-800' :
          job.status === 'failed' ? 'bg-red-100 text-red-800' :
          job.status === 'running' ? 'bg-blue-100 text-blue-800' :
          'bg-gray-100 text-gray-700'
        }`}>
          {job.status}
        </span>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        {[
          ['Salt JID', job.salt_jid ?? '—'],
          ['Target', `${job.target_type}${job.target_id ? ':' + job.target_id.slice(0, 8) : ''}`],
          ['Triggered By', job.triggered_by],
          ['Started', job.started_at ? format(new Date(job.started_at), 'PPpp') : '—'],
          ['Completed', job.completed_at ? format(new Date(job.completed_at), 'PPpp') : '—'],
        ].map(([label, value]) => (
          <div key={label}>
            <p className="text-gray-500 text-xs">{label}</p>
            <p className="font-medium mt-0.5 truncate">{value}</p>
          </div>
        ))}
      </div>

      {rLoading ? (
        <Skeleton rows={4} />
      ) : results && results.items.length > 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 text-sm font-medium text-gray-700">
            Results ({results.total})
          </div>
          <div className="divide-y divide-gray-100">
            {results.items.map((r) => (
              <details key={r.id} className="group">
                <summary className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 text-sm">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${r.status === 'success' || r.exit_code === 0 ? 'bg-green-500' : 'bg-red-500'}`} />
                  <span className="font-mono text-xs text-gray-500">{r.node_id.slice(0, 8)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${r.exit_code === 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    exit {r.exit_code ?? '?'}
                  </span>
                  <span className="ml-auto text-xs text-gray-400">
                    {r.completed_at ? format(new Date(r.completed_at), 'HH:mm:ss') : ''}
                  </span>
                </summary>
                {(r.stdout || r.stderr) && (
                  <div className="px-4 pb-3 space-y-2">
                    {r.stdout && (
                      <pre className="text-xs bg-gray-50 rounded p-2 overflow-auto max-h-40 font-mono whitespace-pre-wrap">
                        {r.stdout}
                      </pre>
                    )}
                    {r.stderr && (
                      <pre className="text-xs bg-red-50 text-red-700 rounded p-2 overflow-auto max-h-40 font-mono whitespace-pre-wrap">
                        {r.stderr}
                      </pre>
                    )}
                  </div>
                )}
              </details>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 3: Verify Execution History**

Navigate to `/executions`. Verify: job list loads, status filter works, clicking a job shows detail with per-node results (expandable stdout/stderr).

- [ ] **Step 4: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/ExecutionHistory.tsx frontend/src/pages/JobDetail.tsx
git commit -m "feat: Execution History + Job Detail pages"
```

---

## Task 10: Final Smoke Test + Build Verification

- [ ] **Step 1: Start backend**

```bash
source /home/dk/Documents/git/kri/.venv/bin/activate
uvicorn fleet_platform.api.main:app --port 8000 &
sleep 2
```

- [ ] **Step 2: Start frontend dev server**

```bash
cd /home/dk/Documents/git/kri/frontend && npm run dev &
sleep 3
```

- [ ] **Step 3: Verify all pages load**

Open `http://localhost:5173/login` in a browser and test each page:
- `/login` — login form, sign in works
- `/fleet` — stats bar + node table, status filter
- `/nodes/:id` — all 4 tabs work (Overview, Drift, SBOM, Executions)
- `/drift` — severity filter works
- `/sbom` — package search works (type "openssl")
- `/groups` — list loads, create form works
- `/groups/:id` — members table loads
- `/executions` — job list loads
- `/executions/:id` — job detail with results

- [ ] **Step 4: Verify TypeScript compiles clean**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 5: Run production build**

```bash
cd /home/dk/Documents/git/kri/frontend && npm run build
```

Expected: `✓ built in Xs` — `dist/` directory created with bundled assets.

- [ ] **Step 6: Stop servers**

```bash
pkill -f uvicorn; pkill -f vite
```

- [ ] **Step 7: Commit final state**

```bash
cd /home/dk/Documents/git/kri
git add frontend/
git commit -m "feat: Plan 6 complete — React frontend production build verified"
```

- [ ] **Step 8: Show git log**

```bash
git log --oneline -10
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Login page with JWT storage → Task 3
- [x] AuthGuard (redirect to /login if no token) → Task 3
- [x] Layout: Sidebar + TopBar with global search → Task 3
- [x] Fleet Dashboard: stats bar + node table + status filter → Task 4
- [x] Node Detail: Overview (hardware, OS, tags), Drift (score + diff + timeline), SBOM (scan meta + components), Executions tabs → Task 5
- [x] Drift Explorer: severity filter + ranked table → Task 6
- [x] SBOM Explorer: fleet-wide package search (debounced 300ms, min 3 chars) → Task 7
- [x] Group Explorer: list + create form (static/dynamic) → Task 8
- [x] Group Detail: metadata + member node table → Task 8
- [x] Execution History: status filter + job table + auto-refresh (15s) → Task 9
- [x] Job Detail: metadata + per-node results with expandable stdout/stderr → Task 9
- [x] React Query stale times per RFC: overview=15s, nodes=30s, node detail=60s, SBOM=300s, drift=60s, executions=10s → Tasks 4-9
- [x] Zustand filter store persists severity/status filters across navigation → Tasks 6, 9
- [x] JWT auto-refresh on 401 → Task 2 (client.ts)
- [x] Production build verified → Task 10

**Type consistency:** All types defined in `types/index.ts` (Task 2) and used consistently in api modules (Task 2) and pages (Tasks 3-9). `Node`, `Group`, `DriftSummary`, `ExecutionJob` — all match backend response shapes confirmed from schema inspection.

**No placeholders:** All step code blocks are complete implementations. No "TBD", no "similar to above".
