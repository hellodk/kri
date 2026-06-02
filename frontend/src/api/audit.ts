import { api } from './client'

export interface AuditEvent {
  id: number
  event_at: string
  actor: string
  action: string
  resource_type: string | null
  resource_id: string | null
  ip_address: string | null
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
}

export interface AuditListParams {
  actor?: string
  action?: string
  resource_type?: string
  from_ts?: string   // ISO datetime string
  to_ts?: string     // ISO datetime string
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
    if (params.from_ts) q.set('from_ts', params.from_ts)
    if (params.to_ts) q.set('to_ts', params.to_ts)
    if (params.page) q.set('page', String(params.page))
    if (params.per_page) q.set('per_page', String(params.per_page))
    return api.get<AuditListResponse>(`/api/v1/audit?${q}`)
  },
}
