import { api } from './client'

export interface NodeSecret {
  key: string
  description: string | null
  created_at: string
  updated_at: string
}

export const nodeSecretsApi = {
  list: (nodeId: string) =>
    api.get<NodeSecret[]>(`/api/v1/nodes/${nodeId}/secrets`),

  upsert: (nodeId: string, key: string, value: string, description?: string) =>
    api.put<NodeSecret>(`/api/v1/nodes/${nodeId}/secrets/${key}`, {
      value,
      description: description ?? null,
    }),

  delete: (nodeId: string, key: string) =>
    api.delete(`/api/v1/nodes/${nodeId}/secrets/${key}`),
}
