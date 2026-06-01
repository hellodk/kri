/**
 * API client for macOS configuration profile management.
 */
import { api } from './client'

export interface MobileconfigProfile {
  id: string
  name: string
  description: string | null
  profile_uuid: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface ProfileComplianceEntry {
  profile_id: string
  node_id: string
  node_hostname: string | null
  status: 'installed' | 'not_installed' | 'pending' | 'failed' | 'unknown'
  last_deployed_at: string | null
}

export interface DeployResponse {
  profile_id: string
  action: string
  node_count: number
  job_ids: string[]
  status: string
}

export const mobileconfigApi = {
  listProfiles: (): Promise<MobileconfigProfile[]> =>
    api.get<MobileconfigProfile[]>('/api/v1/mobileconfig/profiles'),

  createProfile: (data: {
    name: string
    description?: string | null
    payload_xml: string
  }): Promise<MobileconfigProfile> =>
    api.post<MobileconfigProfile>('/api/v1/mobileconfig/profiles', data),

  deleteProfile: (id: string): Promise<void> =>
    api.delete(`/api/v1/mobileconfig/profiles/${id}`),

  assignGroup: (profileId: string, groupId: string): Promise<unknown> =>
    api.post(`/api/v1/mobileconfig/profiles/${profileId}/assign-group`, {
      group_id: groupId,
    }),

  deploy: (
    profileId: string,
    nodeIds: string[],
    action: 'install' | 'remove',
  ): Promise<DeployResponse> =>
    api.post<DeployResponse>(`/api/v1/mobileconfig/profiles/${profileId}/deploy`, {
      node_ids: nodeIds,
      action,
    }),

  compliance: (profileId: string): Promise<ProfileComplianceEntry[]> =>
    api.get<ProfileComplianceEntry[]>(
      `/api/v1/mobileconfig/profiles/${profileId}/compliance`,
    ),
}
