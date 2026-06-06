import { api } from './client'

export interface Credential {
  id: string
  name: string
  kind: 'token' | 'ssh_key' | 'username_password'
  username: string | null
  description: string | null
  created_at: string
  last_used_at: string | null
}

export interface CredentialCreate {
  name: string
  kind: 'token' | 'ssh_key' | 'username_password'
  secret: string
  username?: string
  description?: string
}

export const credentialsApi = {
  list: () => api.get<Credential[]>('/api/v1/credentials'),
  create: (body: CredentialCreate) => api.post<Credential>('/api/v1/credentials', body),
  update: (id: string, body: Partial<CredentialCreate>) =>
    api.patch<Credential>(`/api/v1/credentials/${id}`, body),
  remove: (id: string) => api.delete(`/api/v1/credentials/${id}`),
}
