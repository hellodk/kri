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
