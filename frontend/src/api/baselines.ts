import { api } from './client'
import type { Paginated } from '../types'

// Canonical OS family labels — mirror baseline_loader._VALID_OS_FAMILIES on
// the backend. `null` means OS-agnostic and applies to any node.
export type OsFamily = 'Darwin' | 'Linux' | 'FreeBSD' | 'Windows' | null

export interface Baseline {
  id: string
  name: string
  description: string | null
  target_type: 'global' | 'group' | 'node'
  target_id: string | null
  git_commit_sha: string
  version: number
  created_at: string
  updated_at: string
  os_family: OsFamily
}

export interface BaselineState {
  packages?: Array<{ name: string; version?: string | null }>
  services?: Array<{ name: string; expected: 'running' | 'stopped' }>
}

export interface CaptureResult {
  node_id: string
  hostname: string | null
  minion_id: string
  package_count: number
  packages: Array<{ name: string; version: string | null }>
  services: string[]
  collected_at: string | null
}

export const baselinesApi = {
  list: (params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<Baseline>>(`/api/v1/baselines?${q}`)
  },
  get: (id: string) => api.get<Baseline>(`/api/v1/baselines/${id}`),
  create: (payload: {
    name: string
    description?: string
    target_type: string
    target_id?: string
    state_json: object
    os_family?: OsFamily
  }) => api.post<Baseline>('/api/v1/baselines', { ...payload, git_commit_sha: 'manual' }),
  update: (id: string, payload: {
    name?: string
    description?: string
    target_type?: string
    target_id?: string
    state_json?: object
    // Send empty string to explicitly clear os_family (becomes OS-agnostic).
    os_family?: OsFamily | ''
  }) => api.patch<Baseline>(`/api/v1/baselines/${id}`, payload),
  capture: (nodeId: string) => api.get<CaptureResult>(`/api/v1/baselines/capture/${nodeId}`),
}
