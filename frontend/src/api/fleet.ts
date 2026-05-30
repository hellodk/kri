import { api } from './client'
import type { FleetOverview, Node, NodeDetail, Paginated, Tag } from '../types'

export const fleetApi = {
  overview: () => api.get<FleetOverview>('/api/v1/fleet/overview'),
  nodes: (params: {
    page?: number; per_page?: number; status?: string; sort?: string;
    search?: string; os_version?: string; drift_min?: number; drift_max?: number; tag?: string;
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
}
