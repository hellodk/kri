import { api } from './client'

export interface PlaybookEntry {
  filename: string
  name: string
  description: string | null
  entry_type: 'playbook' | 'role'
  default_vars: Record<string, unknown>
  lint_errors: string[]
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
  extravars: Record<string, unknown>
  status: 'pending' | 'running' | 'completed' | 'failed'
  triggered_by: string
  started_at: string | null
  completed_at: string | null
  stdout: string | null
  rc: number | null
  created_at: string
}

export interface PlaybookStats {
  playbook: string
  run_count: number
  last_duration_seconds: number | null
  avg_duration_seconds: number | null
}

export const playbooksApi = {
  list: () => api.get<PlaybookEntry[]>('/api/v1/ansible/playbooks'),
  run: (playbook: string, target_type: string, target_id: string, extravars: Record<string, unknown>, sshUsername?: string, sshPassword?: string) =>
    api.post<PlaybookRunResponse>('/api/v1/ansible/playbooks/run', { playbook, target_type, target_id, extravars, ssh_username: sshUsername || undefined, ssh_password: sshPassword || undefined }),
  getJob: (jobId: string) => api.get<AnsibleJob>(`/api/v1/ansible/jobs/${jobId}`),
  getStats: (filename: string) =>
    api.get<PlaybookStats>(`/api/v1/ansible/playbooks/${encodeURIComponent(filename)}/stats`),
}
