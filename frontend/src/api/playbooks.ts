import { api } from './client'

export interface PlaybookEntry {
  filename: string
  name: string
  description: string | null
  entry_type: 'playbook' | 'role'
  default_vars: Record<string, unknown>
  var_descriptions?: Record<string, string>
  lint_errors: string[]
  source_dir: string | null
}

export interface PlaybookRunResponse {
  job_id: string
  playbook: string
  target_label: string
  status: string
  message: string
}

export interface AnsibleJob {
  id: string
  playbook: string
  target_type: string
  target_label: string
  target_id: string | null
  extravars: Record<string, unknown>
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  triggered_by: string
  started_at: string | null
  completed_at: string | null
  cancelled_at?: string | null
  stdout: string | null
  rc: number | null
  created_at: string
  celery_task_id?: string | null
}

export interface PlaybookStats {
  playbook: string
  run_count: number
  last_duration_seconds: number | null
  avg_duration_seconds: number | null
}

export const playbooksApi = {
  list: () => api.get<PlaybookEntry[]>('/api/v1/ansible/playbooks'),
  run: (playbook: string, target_type: string, target_id: string, extravars: Record<string, unknown>, sshUsername?: string, sshPassword?: string, verbosity?: number) =>
    api.post<PlaybookRunResponse>('/api/v1/ansible/playbooks/run', { playbook, target_type, target_id, extravars, ssh_username: sshUsername || undefined, ssh_password: sshPassword || undefined, verbosity: verbosity || 0 }),
  getJob: (jobId: string) => api.get<AnsibleJob>(`/api/v1/ansible/jobs/${jobId}`),
  listJobs: (params?: { status?: string; node_id?: string; page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.node_id) q.set('node_id', params.node_id)
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<AnsibleJob[]>(`/api/v1/ansible/jobs?${q}`)
  },
  getStats: (filename: string) =>
    api.get<PlaybookStats>(`/api/v1/ansible/playbooks/${encodeURIComponent(filename)}/stats`),
  cancel: (jobId: string) =>
    api.post<{ job_id: string; status: string; message: string }>(
      `/api/v1/ansible/jobs/${jobId}/cancel`,
      {},
    ),
}

export const playbookSourcesApi = {
  list: () => api.get<{ index: number; type: string; url?: string; path?: string; label?: string }[]>('/api/v1/ansible/sources'),
  add: (payload: { type: string; url?: string; branch?: string; path?: string; label?: string }) =>
    api.post('/api/v1/ansible/sources', payload),
  remove: (index: number) => api.delete(`/api/v1/ansible/sources/${index}`),
  sync: () => api.post<{ results: { url?: string; status: string; error?: string }[] }>('/api/v1/ansible/sources/sync'),
}
