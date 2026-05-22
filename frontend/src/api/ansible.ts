import { api } from './client'

export interface PlatformSettings {
  salt_master_address: string | null
  kri_api_url: string | null
  ssh_bootstrap_username: string | null
  ssh_bootstrap_password: null
  controller_pubkey: string | null
  ansible_endpoint_url: string | null
  playbooks_dir: string | null
  pillar_dir: string | null
  cxone_url: string | null
  sonarqube_url: string | null
  license_policy: string | null
  vnc_enabled?: boolean
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

export interface BootstrapRunSummary {
  id: string
  started_at: string
  finished_at: string | null
  target_ip: string | null
  status: 'running' | 'completed' | 'failed'
  error: string | null
  has_stdout: boolean
}

export interface BootstrapRunDetail {
  id: string
  node_id: string
  started_at: string
  finished_at: string | null
  target_ip: string | null
  status: 'running' | 'completed' | 'failed'
  ansible_stdout: string | null
  error: string | null
}

export interface BootstrapHistoryResponse {
  items: BootstrapRunSummary[]
  total: number
  page: number
  per_page: number
}

export interface FileNode {
  name: string
  path: string
  type: 'file' | 'dir'
  size?: number
  ext?: string
  children?: FileNode[]
}

export interface PlaybookTreeNode {
  type: 'playbook' | 'role' | 'tasks' | 'handlers' | 'defaults' | 'vars' | 'template' | 'file' | 'meta' | 'include'
  path: string
  label: string
  exists: boolean
  task_name?: string
  children?: PlaybookTreeNode[]
}

export interface PlaybookTree {
  filename: string
  nodes: PlaybookTreeNode[]
}

export const ansibleApi = {
  getSettings: () => api.get<PlatformSettings>('/api/v1/settings'),
  updateSettings: (payload: {
    salt_master_address?: string
    kri_api_url?: string
    ssh_bootstrap_username?: string
    ssh_bootstrap_password?: string
    ansible_endpoint_url?: string
    ansible_api_token?: string
    playbooks_dir?: string
    pillar_dir?: string
    cxone_url?: string
    cxone_api_token?: string
    sonarqube_url?: string
    sonarqube_token?: string
    license_policy?: string
    vnc_enabled?: boolean
  }) => api.put<PlatformSettings>('/api/v1/settings', payload),
  bootstrap: (minion_id: string, target_ip: string, sshUsername?: string, sshPassword?: string) =>
    api.post<BootstrapResponse>('/api/v1/ansible/bootstrap', {
      minion_id,
      target_ip,
      ssh_username: sshUsername || undefined,
      ssh_password: sshPassword || undefined,
    }),
  bootstrapStatus: (nodeId: string) =>
    api.get<BootstrapStatus>(`/api/v1/ansible/bootstrap/${nodeId}/status`),
  bootstrapLogs: (nodeId: string) =>
    api.get<{ node_id: string; minion_id: string; bootstrap_status: string; pillar_path: string; pillar: string | null; ansible_stdout: string | null }>(`/api/v1/ansible/bootstrap/${nodeId}/logs`),
  cancelBootstrap: (nodeId: string) =>
    api.post<{ node_id: string; bootstrap_status: string; message: string }>(`/api/v1/ansible/bootstrap/${nodeId}/cancel`, {}),
  bootstrapHistory: (nodeId: string, page = 1, perPage = 20) =>
    api.get<BootstrapHistoryResponse>(`/api/v1/ansible/bootstrap/${nodeId}/history?page=${page}&per_page=${perPage}`),
  bootstrapRunDetail: (nodeId: string, runId: string) =>
    api.get<BootstrapRunDetail>(`/api/v1/ansible/bootstrap/${nodeId}/history/${runId}`),
  playbookContent: (filename: string) =>
    api.get<{ filename: string; content: string }>(`/api/v1/ansible/playbooks/content?filename=${encodeURIComponent(filename)}`),
  collectGrains: (nodeId: string) =>
    api.post<{ task_id: string; node_id: string; status: string }>(`/api/v1/ansible/nodes/${nodeId}/collect-grains`),
  listFiles: () => api.get<{root: string, tree: FileNode[]}>('/api/v1/ansible/files'),
  getFileContent: (path: string) => api.get<{path: string, content: string, size: number}>(`/api/v1/ansible/files/content?path=${encodeURIComponent(path)}`),
  updateFileContent: (path: string, content: string) => api.put<{path: string, saved: boolean}>(`/api/v1/ansible/files/content?path=${encodeURIComponent(path)}`, { content }),
  playbookTree: (filename: string) => api.get<PlaybookTree>(`/api/v1/ansible/playbooks/tree?filename=${encodeURIComponent(filename)}`),
}
