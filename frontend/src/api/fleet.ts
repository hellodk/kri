import { api } from './client'
import type { FleetOverview, Node, NodeDetail, Paginated, Tag } from '../types'

export interface ImportRow {
  minion_id: string
  hostname: string | null
  ip: string | null
  group: string | null
  ssh_user: string | null
  status: 'new' | 'duplicate' | 'invalid'
  reason: string
}

export interface ImportValidateResponse {
  rows: ImportRow[]
  summary: { new: number; duplicate: number; invalid: number; total: number }
}

export interface ImportCommitResponse {
  created: number
  skipped: number
  node_ids: string[]
  bootstrap_queued: number
}

export interface ProcessStatRow {
  pid: number; name: string; cmdline: string | null
  cpu_pct: number | null; mem_rss_bytes: number | null; mem_pct: number | null
  num_threads: number | null; status: string | null; username: string | null
  io_read_bytes: number | null; io_write_bytes: number | null; is_llm: boolean
}

export interface ProcessStatsResponse {
  node_id: string; collected_at: string | null; count: number; processes: ProcessStatRow[]
}

export const fleetApi = {
  overview: () => api.get<FleetOverview>('/api/v1/fleet/overview'),
  nodes: (params: {
    page?: number; per_page?: number; status?: string; sort?: string;
    search?: string; os_version?: string; drift_min?: number; drift_max?: number; tag?: string;
    cpu_min?: number; mem_min?: number;
  }) => {
    const q = new URLSearchParams()
    if (params.page)       q.set('page',       String(params.page))
    if (params.per_page)   q.set('per_page',   String(params.per_page))
    if (params.status)     q.set('status',     params.status)
    if (params.sort)       q.set('sort',       params.sort)
    if (params.search)     q.set('search',     params.search)
    if (params.os_version) q.set('os_version', params.os_version)
    if (params.tag)        q.set('tag',        params.tag)
    if (params.drift_min != null) q.set('drift_min', String(params.drift_min))
    if (params.drift_max != null) q.set('drift_max', String(params.drift_max))
    if (params.cpu_min != null) q.set('cpu_min', String(params.cpu_min))
    if (params.mem_min != null) q.set('mem_min', String(params.mem_min))
    return api.get<Paginated<Node>>(`/api/v1/nodes?${q}`)
  },
  node: (id: string) => api.get<NodeDetail>(`/api/v1/nodes/${id}`),
  createNode: (data: { minion_id: string; hostname?: string; ip_address?: string; hardware_model?: string; os_version?: string }) =>
    api.post<NodeDetail>('/api/v1/nodes', data),
  updateNode: (id: string, data: {
    hostname?: string; ip_address?: string; hardware_model?: string; os_version?: string;
    ssh_username?: string; ssh_password?: string; ssh_auth_mode?: string; ssh_key?: string;
    vnc_password?: string;
  }) =>
    api.patch<NodeDetail>(`/api/v1/nodes/${id}`, data),
  deleteNode: (id: string) =>
    api.delete(`/api/v1/nodes/${id}`),
  addTag: (nodeId: string, key: string, value: string) =>
    api.post<Tag>(`/api/v1/nodes/${nodeId}/tags`, { key, value }),
  removeTag: (nodeId: string, key: string) =>
    api.delete(`/api/v1/nodes/${nodeId}/tags/${key}`),
  maintenanceMode: (nodeId: string, enabled: boolean) =>
    api.patch<NodeDetail>(`/api/v1/nodes/${nodeId}/maintenance`, { enabled }),
  importValidate: (body: { source: string; text?: string; csv_content?: string; mapping?: Record<string, string> }) =>
    api.post<ImportValidateResponse>('/api/v1/fleet/nodes/import/validate', body),
  importCommit: (body: { rows: ImportRow[]; group_id?: string; ssh_username?: string; ssh_password?: string; auto_bootstrap?: boolean }) =>
    api.post<ImportCommitResponse>('/api/v1/fleet/nodes/import/commit', body),
  processStats: (nodeId: string, params: { sort?: 'mem_rss_bytes' | 'cpu_pct'; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.sort) q.set('sort', params.sort)
    if (params.limit) q.set('limit', String(params.limit))
    const qs = q.toString()
    return api.get<ProcessStatsResponse>(`/api/v1/nodes/${nodeId}/process_stats${qs ? `?${qs}` : ''}`)
  },
}
