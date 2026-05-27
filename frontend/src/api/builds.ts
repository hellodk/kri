// frontend/src/api/builds.ts
import { api } from './client'

export interface JenkinsBuild {
  id: string
  job_name: string
  build_number: number
  result: 'SUCCESS' | 'FAILURE' | 'UNSTABLE' | 'ABORTED' | 'NOT_BUILT'
  duration_ms: number | null
  started_at: string
  test_pass: number | null
  test_fail: number | null
  test_total: number | null
  node_name: string | null
  branch: string | null
}

export const buildsApi = {
  listRecent: (limit = 50) =>
    api.get<JenkinsBuild[]>(`/api/v1/builds/recent?limit=${limit}`),
  triggerDigest: () =>
    api.post<{ status: string; task_id: string }>('/api/v1/builds/digest/send-now', {}),
}
