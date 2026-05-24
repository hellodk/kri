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
