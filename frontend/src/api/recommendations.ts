import { api } from './client'

export interface Recommendation {
  id: string
  generated_at: string
  content: string
  model: string
  provider: string
  node_count: number
  generated_by: string
}

export const recommendationsApi = {
  getLatest: (): Promise<Recommendation | null> =>
    api.get<Recommendation | undefined>('/api/v1/recommendations').then((r) => r ?? null),
  generate: () => api.post<Recommendation>('/api/v1/recommendations/generate'),
}

export function getLatestRecommendation(): Promise<Recommendation | null> {
  return recommendationsApi.getLatest()
}

export function generateRecommendations(): Promise<Recommendation> {
  return recommendationsApi.generate()
}
