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
