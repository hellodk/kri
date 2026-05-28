import { api } from './client'
import type { Paginated, SBOMComponent, SBOMDelta, SBOMScan, SBOMSearchResult } from '../types'

export interface LicenseSummary {
  copyleft_count: number
  copyleft_packages: Array<{ name: string; version: string; license: string; node_id: string; purl: string }>
  unknown_license_count: number
  top_licenses: Array<{ license: string; count: number }>
  total_distinct_licenses: number
}

export const sbomApi = {
  latestScan: (nodeId: string) => api.get<SBOMScan>(`/api/v1/sbom/${nodeId}/latest`),
  scans: (nodeId: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<SBOMScan>>(`/api/v1/sbom/${nodeId}/scans?${q}`)
  },
  components: (nodeId: string, scanId: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<SBOMComponent>>(
      `/api/v1/sbom/${nodeId}/scans/${scanId}/components?${q}`
    )
  },
  search: (q: string) =>
    api.get<SBOMSearchResult[]>(`/api/v1/sbom/search?q=${encodeURIComponent(q)}`),
  browse: () =>
    api.get<SBOMSearchResult[]>('/api/v1/sbom/browse'),
  getDelta: (nodeId: string) =>
    api.get<SBOMDelta>(`/api/v1/sbom/delta/${nodeId}`),
  getLicenseSummary: () =>
    api.get<LicenseSummary>('/api/v1/sbom/licenses/summary'),
}
