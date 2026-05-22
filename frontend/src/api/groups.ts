import { api } from './client'
import type { Group, Node, Paginated } from '../types'

export interface GroupCredentials {
  group_id: string
  ssh_username: string | null
  has_ssh_password: boolean
  has_ssh_key: boolean
  ssh_auth_mode: string
  session_max_mins: number
  session_retention_days: number
  credential_source: string
}

export const groupsApi = {
  list: (params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<Group>>(`/api/v1/groups?${q}`)
  },
  get: (id: string) => api.get<Group>(`/api/v1/groups/${id}`),
  create: (payload: { name: string; description?: string; type: string; predicate?: unknown }) =>
    api.post<Group>('/api/v1/groups', payload),
  members: (id: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<Node>>(`/api/v1/groups/${id}/nodes?${q}`)
  },
  addMember: (groupId: string, nodeId: string) =>
    api.post(`/api/v1/groups/${groupId}/members`, { node_id: nodeId }),
  removeMember: (groupId: string, nodeId: string) =>
    api.delete(`/api/v1/groups/${groupId}/members/${nodeId}`),
  getCredentials: (groupId: string) =>
    api.get<GroupCredentials>(`/api/v1/groups/${groupId}/credentials`),
  updateCredentials: (
    groupId: string,
    payload: {
      ssh_username?: string | null
      ssh_password?: string | null
      ssh_auth_mode?: string | null
      ssh_key?: string | null
      session_max_mins?: number | null
      session_retention_days?: number | null
    },
  ) => api.patch<GroupCredentials>(`/api/v1/groups/${groupId}/credentials`, payload),
}
