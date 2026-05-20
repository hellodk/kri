import { api } from './client'
import type { Paginated } from '../types'

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
}

export interface BaselineState {
  packages?: Array<{ name: string; version?: string | null }>
  services?: Array<{ name: string; expected: 'running' | 'stopped' }>
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
  }) => api.post<Baseline>('/api/v1/baselines', { ...payload, git_commit_sha: 'manual' }),
}
