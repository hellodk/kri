import { api } from './client'

export interface Credential {
  id: string
  name: string
  kind: 'token' | 'ssh_key' | 'username_password'
  username: string | null
  description: string | null
  created_at: string
  last_used_at: string | null
  // Reference counts / secret presence — populated by the backend when
  // available (#1002); treated as optional so the UI degrades gracefully
  // if a given API version doesn't return them yet.
  has_secret?: boolean
  node_count?: number
  group_count?: number
}

export interface CredentialCreate {
  name: string
  kind: 'token' | 'ssh_key' | 'username_password'
  secret: string
  username?: string
  description?: string
}

export interface CredentialNodeUsage {
  id: string
  minion_id: string
  hostname: string | null
  source: string // 'node' | 'group:<name>'
}

export interface CredentialNodesResponse {
  credential_id: string
  count: number
  nodes: CredentialNodeUsage[]
}

export const credentialsApi = {
  list: () => api.get<Credential[]>('/api/v1/credentials'),
  create: (body: CredentialCreate) => api.post<Credential>('/api/v1/credentials', body),
  update: (id: string, body: Partial<CredentialCreate>) =>
    api.patch<Credential>(`/api/v1/credentials/${id}`, body),
  // Resolution-aware reverse lookup: nodes whose effective credential is this one (#700).
  nodes: (id: string) => api.get<CredentialNodesResponse>(`/api/v1/credentials/${id}/nodes`),
  // force=true detaches referencing nodes/groups (FK -> NULL) past the #726 guard.
  remove: (id: string, force = false) =>
    api.delete(`/api/v1/credentials/${id}${force ? '?force=true' : ''}`),
}
