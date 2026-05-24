import { api } from './client'

export interface SaltKeys {
  accepted: string[]
  pending: string[]
  rejected: string[]
  denied: string[]
  pending_count: number
}

export const saltKeysApi = {
  list: () => api.get<SaltKeys>('/api/v1/salt/keys'),
  accept: (minionId: string) => api.post<{ status: string; minion_id: string }>(`/api/v1/salt/keys/${minionId}/accept`, {}),
  reject: (minionId: string) => api.post<{ status: string; minion_id: string }>(`/api/v1/salt/keys/${minionId}/reject`, {}),
  delete: (minionId: string) => api.delete(`/api/v1/salt/keys/${minionId}`),
}
