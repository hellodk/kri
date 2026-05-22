import { api } from './client'
import type { PlaybookEntry } from './playbooks'

export interface PlaybookSource {
  index: number
  type: 'local' | 'git'
  path?: string | null
  url?: string | null
  branch?: string | null
  label?: string | null
  local_path?: string | null
}

export interface SyncResult {
  results: Array<{
    index: number
    url: string
    status: 'ok' | 'error'
    error?: string
  }>
}

export interface PlaybookSourceValidateRequest {
  type: 'local' | 'git'
  path?: string
  url?: string
  branch?: string
  ssh_key?: string
  token?: string
}

export interface PlaybookSourceValidateResponse {
  valid: boolean
  error?: string
  warnings: string[]
  playbook_count: number
  role_count: number
  entries: PlaybookEntry[]
  logs: string[]
}

export const playbookSourcesApi = {
  list: () => api.get<PlaybookSource[]>('/api/v1/ansible/sources'),
  add: (source: {
    type: string
    path?: string
    url?: string
    branch?: string
    label?: string
    local_path?: string
    ssh_key?: string
    token?: string
  }) => api.post<PlaybookSource>('/api/v1/ansible/sources', source),
  remove: (index: number) => api.delete(`/api/v1/ansible/sources/${index}`),
  sync: () => api.post<SyncResult>('/api/v1/ansible/sources/sync', {}),
  importCsv: (csv: string) =>
    api.post<{ added: number }>('/api/v1/ansible/sources/import', { csv }),
  validate: (payload: PlaybookSourceValidateRequest) =>
    api.post<PlaybookSourceValidateResponse>('/api/v1/ansible/sources/validate', payload),
}
