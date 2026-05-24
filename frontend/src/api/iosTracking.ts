import { api } from './client'

export interface IOSNode {
  node_id: string
  minion_id: string
  hostname: string | null
  status: string
  macos_version: string | null
  xcode_version: string | null
  cert_count: number
  next_cert_expiry: string | null
  jenkins_status: string | null
}

export interface Certificate {
  id: string
  node_id: string
  name: string
  cert_type: string
  team_id: string | null
  expiry_date: string
  fingerprint: string | null
  created_at: string
  updated_at: string
}

export interface JenkinsAgent {
  id: string
  node_id: string
  jenkins_url: string
  agent_name: string
  status: 'online' | 'offline' | 'unknown'
  last_checked_at: string | null
  created_at: string
}

export interface IOSNodeDetail {
  node_id: string
  minion_id: string
  hostname: string | null
  status: string
  macos_version: string | null
  xcode_version: string | null
  certificates: Certificate[]
  jenkins_agent: JenkinsAgent | null
}

export interface IOSNodesResponse {
  items: IOSNode[]
  total: number
}

export interface ExpiringCertsResponse {
  items: Certificate[]
  total: number
  days: number
}

export interface AddCertBody {
  name: string
  cert_type: string
  team_id?: string | null
  expiry_date: string
  fingerprint?: string | null
}

export interface UpsertJenkinsBody {
  jenkins_url: string
  agent_name: string
}

export const iosTrackingApi = {
  listNodes: () => api.get<IOSNodesResponse>('/api/v1/ios/nodes'),
  getNode: (nodeId: string) => api.get<IOSNodeDetail>(`/api/v1/ios/nodes/${nodeId}`),

  addCertificate: (nodeId: string, body: AddCertBody) =>
    api.post<Certificate>(`/api/v1/ios/nodes/${nodeId}/certificates`, body),
  deleteCertificate: (certId: string) => api.delete(`/api/v1/ios/certificates/${certId}`),

  getJenkinsAgent: (nodeId: string) =>
    api.get<JenkinsAgent>(`/api/v1/ios/nodes/${nodeId}/jenkins`),
  upsertJenkinsAgent: (nodeId: string, body: UpsertJenkinsBody) =>
    api.put<JenkinsAgent>(`/api/v1/ios/nodes/${nodeId}/jenkins`, body),
  checkJenkinsNow: (nodeId: string) =>
    api.post<JenkinsAgent>(`/api/v1/ios/nodes/${nodeId}/jenkins/check`),

  getExpiringCerts: (days = 30) =>
    api.get<ExpiringCertsResponse>(`/api/v1/ios/expiring-certs?days=${days}`),
}
