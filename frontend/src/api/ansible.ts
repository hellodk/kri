import { api } from './client'

export interface PlatformSettings {
  salt_master_address: string | null
  ssh_bootstrap_username: string | null
  ssh_bootstrap_password: null
  controller_pubkey: string | null
  ansible_endpoint_url: string | null
  playbooks_dir: string | null
  pillar_dir: string | null
}

export interface BootstrapResponse {
  node_id: string
  minion_id: string
  job_id: string
  bootstrap_status: string
  message: string
}

export interface BootstrapStatus {
  node_id: string
  minion_id: string
  bootstrap_status: 'pending' | 'bootstrapping' | 'completed' | 'failed'
  bootstrap_ip: string | null
  bootstrap_error: string | null
}

export const ansibleApi = {
  getSettings: () => api.get<PlatformSettings>('/api/v1/settings'),
  updateSettings: (payload: {
    salt_master_address?: string
    ssh_bootstrap_username?: string
    ssh_bootstrap_password?: string
    ansible_endpoint_url?: string
    ansible_api_token?: string
    playbooks_dir?: string
    pillar_dir?: string
  }) => api.put<PlatformSettings>('/api/v1/settings', payload),
  bootstrap: (minion_id: string, target_ip: string) =>
    api.post<BootstrapResponse>('/api/v1/ansible/bootstrap', { minion_id, target_ip }),
  bootstrapStatus: (nodeId: string) =>
    api.get<BootstrapStatus>(`/api/v1/ansible/bootstrap/${nodeId}/status`),
  bootstrapLogs: (nodeId: string) =>
    api.get<{ node_id: string; minion_id: string; bootstrap_status: string; pillar_path: string; pillar: string | null; ansible_stdout: string | null }>(`/api/v1/ansible/bootstrap/${nodeId}/logs`),
  playbookContent: (filename: string) =>
    api.get<{ filename: string; content: string }>(`/api/v1/ansible/playbooks/content?filename=${encodeURIComponent(filename)}`),
}
