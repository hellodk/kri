import { ApiError, api } from './client'

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

// ── Streaming query (SSE) ────────────────────────────────────────────────────
// EventSource cannot POST and cannot send custom headers (Authorization),
// so the streaming endpoint is consumed via fetch() + a ReadableStream
// reader. The wire format is SSE-compatible (each event is a single
// `data: <json>\n\n` line), which keeps it interoperable with curl, nginx
// proxy buffering, and any future generic SSE client.

export interface StreamDelta {
  type: 'delta'
  text: string
}

export interface StreamDone {
  type: 'done'
  query_id: string
  intent: string
  model_used: string
  endpoint_name: string
  input_tokens: number
  output_tokens: number
  duration_ms: number
  error?: string
}

export interface StreamError {
  type: 'error'
  error: string
}

export type StreamEvent = StreamDelta | StreamDone | StreamError

export interface StreamCallbacks {
  onDelta?: (text: string, fullText: string) => void
  onDone?: (final: StreamDone) => void
  onError?: (message: string) => void
}

/**
 * Stream an LLM query response via SSE. Returns an AbortController whose
 * .abort() method cancels both the client read loop and the upstream LLM
 * call (FastAPI propagates client disconnects).
 */
export function streamQuery(
  data: LLMQueryRequest,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController()
  void runStream(data, callbacks, controller).catch((err) => {
    if (controller.signal.aborted) return
    callbacks.onError?.(err instanceof Error ? err.message : String(err))
  })
  return controller
}

async function runStream(
  data: LLMQueryRequest,
  callbacks: StreamCallbacks,
  controller: AbortController,
): Promise<void> {
  const token = localStorage.getItem('access_token') || ''
  const res = await fetch('/api/v1/llm/query/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(data),
    signal: controller.signal,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(
      res.status,
      (body as { detail?: string }).detail ?? res.statusText,
      (body as { error_code?: string }).error_code ?? null,
    )
  }
  if (!res.body) {
    throw new Error('Stream response had no body')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let fullText = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by `\n\n`. Multiple frames may arrive in a
    // single chunk; partial trailing frames stay in the buffer for the
    // next iteration.
    let sep = buffer.indexOf('\n\n')
    while (sep !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data:')) || ''
      const payload = line.replace(/^data:\s*/, '')
      if (payload === '[DONE]') return
      if (!payload) {
        sep = buffer.indexOf('\n\n')
        continue
      }
      try {
        const ev = JSON.parse(payload) as StreamEvent
        if (ev.type === 'delta') {
          fullText += ev.text
          callbacks.onDelta?.(ev.text, fullText)
        } else if (ev.type === 'done') {
          callbacks.onDone?.(ev)
        } else if (ev.type === 'error') {
          callbacks.onError?.(ev.error)
        }
      } catch {
        // Ignore malformed frames; the server should never emit them but
        // a partial unicode boundary mid-frame is theoretically possible.
      }
      sep = buffer.indexOf('\n\n')
    }
  }
}
