import { api } from './client'

export interface LibraryEntry {
  filename: string
  name: string
  description: string | null
  entry_type: string
  default_vars: Record<string, unknown>
  var_descriptions: Record<string, string>
  lint_errors: string[]
  source_dir: string | null
  source_key: string
  source_label: string
  enabled: boolean
  catalog_id: string | null
  auto_disabled_at: string | null
}

export interface EnableRequest {
  source_key: string
  source_label: string
  filename: string
  entry_type: string
}

export const libraryApi = {
  list: () => api.get<LibraryEntry[]>('/api/v1/ansible/playbooks/library'),

  enable: (payload: EnableRequest) =>
    api.post<{ id: string; enabled: boolean }>('/api/v1/ansible/playbooks/library/enable', payload),

  disable: (catalog_id: string) =>
    api.post<{ id: string; enabled: boolean }>('/api/v1/ansible/playbooks/library/disable', { catalog_id }),

  enableSource: (source_key: string) =>
    api.post<{ source_key: string; enabled_count: number }>('/api/v1/ansible/playbooks/library/enable-source', { source_key }),

  addFavorite: (catalog_id: string) =>
    api.post<{ catalog_id: string; favorited: boolean }>(`/api/v1/ansible/playbooks/library/favorites/${catalog_id}`, {}),

  removeFavorite: (catalog_id: string) =>
    api.delete(`/api/v1/ansible/playbooks/library/favorites/${catalog_id}`),
}
