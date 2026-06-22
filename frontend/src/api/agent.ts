import { ApiError } from './client'

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
  const token = localStorage.getItem('access_token') || ''
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
