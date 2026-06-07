import { api } from './client'

/**
 * Response — never includes api_password_enc, ssh_key_enc, or ssh_password_enc.
 * Provision lifecycle fields added in #556 (master-lifecycle epic).
 * SSoT api_url derivation added in #562: api_url is read-only/computed from
 * address + salt_api_port + use_tls.
 */
export interface SaltMaster {
  id: string
  name: string
  enabled: boolean
  is_default: boolean
  address: string
  publish_port: number
  ret_port: number
  /** SSoT fields (#562) — api_url is derived from these */
  salt_api_port: number
  use_tls: boolean
  /** Read-only derived field — computed server-side from address + salt_api_port + use_tls */
  api_url: string | null
  api_user: string | null
  /** api_password_enc intentionally excluded from response */
  /** control_mode / api_eauth / token_delivery are server-defaults; visible but not editable */
  control_mode: string
  api_eauth: string | null
  token_delivery: string
  tls_verify: boolean
  auto_accept: boolean
  status: string
  last_checked_at: string | null
  last_error: string | null
  checks: Array<{ check: string; status: string; detail: string; latency_ms: number }> | null
  /** Provision lifecycle (#556) */
  provision_status: string
  os_family: string | null
  salt_version: string | null
  last_provisioned_at: string | null
  provision_error: string | null
  /** SSH host/user readable; ssh_key_enc/ssh_password_enc intentionally excluded */
  ssh_host: string | null
  ssh_user: string | null
  node_id: string | null
  created_at: string
  updated_at: string
}

/**
 * Create payload — api_url is NOT accepted (derived server-side).
 * control_mode / api_eauth / token_delivery are NOT accepted (server-defaults).
 */
export interface SaltMasterCreate {
  name: string
  address: string
  enabled?: boolean
  is_default?: boolean
  publish_port?: number
  ret_port?: number
  /** SSoT fields — api_url is DERIVED from these; never send api_url directly */
  salt_api_port?: number
  use_tls?: boolean
  api_user?: string | null
  /** Write-only: stored encrypted, never returned. */
  api_password?: string | null
  tls_verify?: boolean
  auto_accept?: boolean
  /** SSH creds for provisioning (write-only — stored encrypted). */
  ssh_host?: string | null
  ssh_user?: string | null
  /** Write-only: stored encrypted, never returned. */
  ssh_key?: string | null
  /** Write-only: stored encrypted, never returned. */
  ssh_password?: string | null
  node_id?: string | null
}

/**
 * Update payload — all fields optional.
 * api_url is NOT accepted (derived server-side).
 * control_mode / api_eauth / token_delivery are NOT accepted (server-defaults).
 */
export interface SaltMasterUpdate {
  name?: string
  address?: string
  enabled?: boolean
  is_default?: boolean
  publish_port?: number
  ret_port?: number
  /** SSoT fields — api_url is DERIVED from these; never send api_url directly */
  salt_api_port?: number
  use_tls?: boolean
  api_user?: string | null
  /** Write-only: stored encrypted, never returned. */
  api_password?: string | null
  tls_verify?: boolean
  auto_accept?: boolean
  /** SSH creds for provisioning (write-only — stored encrypted). */
  ssh_host?: string | null
  ssh_user?: string | null
  /** Write-only: stored encrypted, never returned. */
  ssh_key?: string | null
  /** Write-only: stored encrypted, never returned. */
  ssh_password?: string | null
  node_id?: string | null
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

/** Response for a single master_provision_run record. */
export interface MasterProvisionRunResponse {
  id: string
  salt_master_id: string
  action: string
  status: string
  started_at: string
  finished_at: string | null
  ansible_stdout: string | null
  error: string | null
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
