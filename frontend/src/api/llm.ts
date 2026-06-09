import { api } from './client'

export type LLMProvider = 'openai_compat' | 'anthropic' | 'ollama' | 'vllm' | 'llamacpp'
export type LLMIntent = 'salt_state' | 'ansible_playbook' | 'fleet_command' | 'explain' | 'fleet_query' | 'auto'

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
  model_context_length: number | null
  model_capabilities: string[]
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

export interface ChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface LLMQueryRequest {
  prompt: string
  intent: LLMIntent
  endpoint_id?: string | null
  history?: ChatHistoryMessage[]
}

export interface LLMQueryResponse {
  query_id: string
  intent: string
  result: string
  model_used: string
  endpoint_name: string
  input_tokens: number
  output_tokens: number
  duration_ms: number
}

export interface LLMQueryLogEntry {
  id: string
  intent: string
  prompt: string
  model_used: string | null
  duration_ms: number | null
  error: string | null
  created_at: string
}

export const llmApi = {
  list: () => api.get<LLMEndpoint[]>('/api/v1/llm/endpoints'),
  create: (data: LLMEndpointCreate) => api.post<LLMEndpoint>('/api/v1/llm/endpoints', data),
  update: (id: string, data: LLMEndpointUpdate) =>
    api.put<LLMEndpoint>(`/api/v1/llm/endpoints/${id}`, data),
  delete: (id: string) => api.delete(`/api/v1/llm/endpoints/${id}`),
  test: (id: string) =>
    api.post<LLMEndpointTestResult>(`/api/v1/llm/endpoints/${id}/test`),
  submitQuery: (data: LLMQueryRequest) => api.post<LLMQueryResponse>('/api/v1/llm/query', data),
  listQueries: () => api.get<LLMQueryLogEntry[]>('/api/v1/llm/queries'),
  discoverModels: (url: string, provider: string) =>
    api.post<{ models: Array<{ id: string; name: string; healthy: boolean; latency_ms: number | null }> }>(
      '/api/v1/llm/discover-models',
      { url, provider }
    ),
}
