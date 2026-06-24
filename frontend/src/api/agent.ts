import { ApiError, api } from './client'
import { getAccessToken } from '../stores/authStore'

// ── Quarantined artifacts (#713) ─────────────────────────────────────────────

export interface ArtifactSummary {
  id: string
  session_id: string
  filename: string
  size: number
  created_at: number | null
  metadata: { kind?: string; created_by?: string } & Record<string, unknown>
}

export interface ArtifactDetail {
  content: string
  metadata: Record<string, unknown>
}

export interface ArtifactDiff {
  unified: string
  added: number
  removed: number
  is_new: boolean
  original: string
  modified: string
}

export interface AgentAction {
  id: string
  tool_name: string
  params: Record<string, unknown>
  requested_by: string
  status: string
  target_count: number | null
  co_sign_required: boolean
  approved_by: string | null
  co_signed_by: string | null
  dry_run_result: unknown
  created_at: string | null
}

export const actionApi = {
  list: () => api.get<{ actions: AgentAction[] }>('/api/v1/agent/actions'),
  approve: (id: string) => api.post<{ status: string; message?: string }>(`/api/v1/agent/actions/${id}/approve`, {}),
  reject: (id: string) => api.post<{ status: string }>(`/api/v1/agent/actions/${id}/reject`, {}),
}

export const artifactApi = {
  list: () => api.get<{ artifacts: ArtifactSummary[] }>('/api/v1/agent/artifacts'),
  get: (sessionId: string, filename: string) =>
    api.get<ArtifactDetail>(`/api/v1/agent/artifacts/${encodeURIComponent(sessionId)}/${encodeURIComponent(filename)}`),
  diff: (sessionId: string, filename: string, target?: string) =>
    api.get<ArtifactDiff>(
      `/api/v1/agent/artifacts/${encodeURIComponent(sessionId)}/${encodeURIComponent(filename)}/diff` +
        (target ? `?target=${encodeURIComponent(target)}` : ''),
    ),
}

// ── Agent run (SSE) ──────────────────────────────────────────────────────────
// The agent endpoint streams structured events (not plain text deltas):
// session_start → (step_start → tool_call → tool_result)* → final | limit_reached
// → done. Same `data: <json>\n\n` wire format as the LLM query stream so it is
// consumable by curl and survives proxy buffering.

export interface AgentRunRequest {
  prompt: string
  endpoint_id?: string | null
}

export interface AgentSessionStart {
  type: 'session_start'
  session_id: string
  model: string
}

export interface AgentStepStart {
  type: 'step_start'
  iteration: number
}

export interface AgentToolCall {
  type: 'tool_call'
  name: string
  args: Record<string, unknown>
  n: number
}

export interface AgentToolResult {
  type: 'tool_result'
  name: string
  ok: boolean
  status: string
  result: unknown
  error: string | null
  cached: boolean
}

export interface AgentAwaitingApproval {
  type: 'awaiting_approval'
  name: string
  n: number
}

export interface AgentFinal {
  type: 'final'
  text: string
  iterations: number
}

export interface AgentLimitReached {
  type: 'limit_reached'
  limit: string
  value: number
}

export interface AgentDone {
  type: 'done'
  session_id: string
  query_id: string | null
  status: string
  iterations: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  duration_ms: number
}

export interface AgentErrorEvent {
  type: 'error'
  error: string
}

export type AgentEvent =
  | AgentSessionStart
  | AgentStepStart
  | AgentToolCall
  | AgentToolResult
  | AgentAwaitingApproval
  | AgentFinal
  | AgentLimitReached
  | AgentDone
  | AgentErrorEvent

export interface AgentCallbacks {
  onEvent?: (ev: AgentEvent) => void
  onError?: (message: string) => void
}

/**
 * Run a tool-using agent turn via SSE. Returns an AbortController whose
 * .abort() cancels both the client read loop and the upstream run.
 */
export function streamAgent(data: AgentRunRequest, callbacks: AgentCallbacks): AbortController {
  const controller = new AbortController()
  void runAgentStream(data, callbacks, controller).catch((err) => {
    if (controller.signal.aborted) return
    callbacks.onError?.(err instanceof Error ? err.message : String(err))
  })
  return controller
}

async function runAgentStream(
  data: AgentRunRequest,
  callbacks: AgentCallbacks,
  controller: AbortController,
): Promise<void> {
  const token = getAccessToken() || ''
  const res = await fetch('/api/v1/agent/run/stream', {
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
  if (!res.body) throw new Error('Stream response had no body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep = buffer.indexOf('\n\n')
    while (sep !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data:')) || ''
      const payload = line.replace(/^data:\s*/, '')
      if (payload === '[DONE]') return
      if (payload) {
        try {
          callbacks.onEvent?.(JSON.parse(payload) as AgentEvent)
        } catch {
          // Ignore malformed frames.
        }
      }
      sep = buffer.indexOf('\n\n')
    }
  }
}
