import { api } from './client'

/** Response — never includes api_password or api_password_enc. */
export interface SaltMaster {
  id: string
  name: string
  enabled: boolean
  is_default: boolean
  address: string
  publish_port: number
  ret_port: number
  control_mode: string
  api_url: string | null
  api_user: string | null
  /** api_password_enc intentionally excluded from response */
  api_eauth: string | null
  token_delivery: string
  status: string
  last_checked_at: string | null
  last_error: string | null
  checks: Array<{ check: string; status: string; detail: string; latency_ms: number }> | null
  created_at: string
  updated_at: string
}

/** Create payload — api_password is write-only plaintext. */
export interface SaltMasterCreate {
  name: string
  address: string
  enabled?: boolean
  is_default?: boolean
  publish_port?: number
  ret_port?: number
  control_mode?: string
  api_url?: string | null
  api_user?: string | null
  /** Write-only: stored encrypted, never returned. */
  api_password?: string | null
  api_eauth?: string | null
  token_delivery?: string
}

/** Update payload — all fields optional. */
export interface SaltMasterUpdate {
  name?: string
  address?: string
  enabled?: boolean
  is_default?: boolean
  publish_port?: number
  ret_port?: number
  control_mode?: string
  api_url?: string | null
  api_user?: string | null
  /** Write-only: stored encrypted, never returned. */
  api_password?: string | null
  api_eauth?: string | null
  token_delivery?: string
}

export interface SaltMasterHealthResponse {
  status: string
  last_checked_at: string | null
  last_error: string | null
  checks: Array<{ check: string; status: string; detail: string; latency_ms: number }>
}

export interface SaltMasterTestResponse {
  status: string
  checks: Array<{ check: string; status: string; detail: string; latency_ms: number }>
}

export const saltMastersApi = {
  list: () => api.get<SaltMaster[]>('/api/v1/salt/masters'),
  get: (id: string) => api.get<SaltMaster>(`/api/v1/salt/masters/${id}`),
  create: (body: SaltMasterCreate) => api.post<SaltMaster>('/api/v1/salt/masters', body),
  update: (id: string, body: SaltMasterUpdate) =>
    api.patch<SaltMaster>(`/api/v1/salt/masters/${id}`, body),
  remove: (id: string) => api.delete(`/api/v1/salt/masters/${id}`),
  test: (id: string) =>
    api.post<SaltMasterTestResponse>(`/api/v1/salt/masters/${id}/test`, {}),
  health: (id: string) =>
    api.get<SaltMasterHealthResponse>(`/api/v1/salt/masters/${id}/health`),
}
