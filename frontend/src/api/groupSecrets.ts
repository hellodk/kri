import { api } from './client'

export interface GroupSecret {
  key: string
  description: string | null
  created_at: string
  updated_at: string
}

export const groupSecretsApi = {
  list: (groupId: string) =>
    api.get<GroupSecret[]>(`/api/v1/groups/${groupId}/secrets`),

  upsert: (groupId: string, key: string, value: string, description?: string) =>
    api.put<GroupSecret>(`/api/v1/groups/${groupId}/secrets/${key}`, {
      value,
      description: description ?? null,
    }),

  delete: (groupId: string, key: string) =>
    api.delete(`/api/v1/groups/${groupId}/secrets/${key}`),
}
