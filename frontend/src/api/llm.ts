import { api } from './client'

export type LLMProvider = 'openai_compat' | 'anthropic'

export interface LLMEndpoint {
  id: string
  name: string
  provider: LLMProvider
  base_url: string | null
  model: string
  max_tokens: number
  is_default: boolean
  enabled: boolean
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export interface LLMEndpointCreate {
  name: string
  provider: LLMProvider
  base_url?: string | null
  model: string
  max_tokens?: number
  is_default?: boolean
  enabled?: boolean
  api_key?: string | null
}

export type LLMEndpointUpdate = Partial<LLMEndpointCreate>

export interface LLMEndpointTestResult {
  ok: boolean
  latency_ms: number | null
  error: string | null
}

export const llmApi = {
  list: () => api.get<LLMEndpoint[]>('/api/v1/llm/endpoints'),
  create: (data: LLMEndpointCreate) => api.post<LLMEndpoint>('/api/v1/llm/endpoints', data),
  update: (id: string, data: LLMEndpointUpdate) =>
    api.put<LLMEndpoint>(`/api/v1/llm/endpoints/${id}`, data),
  delete: (id: string) => api.delete(`/api/v1/llm/endpoints/${id}`),
  test: (id: string) =>
    api.post<LLMEndpointTestResult>(`/api/v1/llm/endpoints/${id}/test`),
}

