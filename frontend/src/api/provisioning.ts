import { api } from './client'
import { getAccessToken } from '../stores/authStore'

export interface ProvisioningProfile {
  id: string
  name: string
  filename: string
  bundle_id: string | null
  team_name: string | null
  expiry_date: string | null
  profile_type: 'development' | 'adhoc' | 'distribution'
  description: string | null
  uploaded_by: string
  created_at: string
}

export const provisioningApi = {
  list: () =>
    api.get<{ items: ProvisioningProfile[]; total: number }>('/api/v1/provisioning'),

  upload: (name: string, file: File, description?: string) => {
    const form = new FormData()
    form.append('name', name)
    form.append('file', file)
    if (description) form.append('description', description)
    return api.postForm<ProvisioningProfile>('/api/v1/provisioning', form)
  },

  download: (id: string, filename: string) => {
    const token = getAccessToken()
    return fetch(`/api/v1/provisioning/${id}/download`, {
      headers: { Authorization: `Bearer ${token ?? ''}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Download failed: ${r.status} ${r.statusText}`)
        return r.blob()
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => { throw err })
  },

  delete: (id: string) => api.delete(`/api/v1/provisioning/${id}`),
}
