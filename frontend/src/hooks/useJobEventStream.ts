import { useEffect, useRef } from 'react'
import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { getAccessToken } from '../stores/authStore'

// Live job-event push (#756 / ARC-11).
//
// Subscribes to the server's SSE stream (`GET /api/v1/events/jobs/stream`) and,
// on each pushed job-state transition, invalidates the affected React Query
// caches so existing `useQuery` hooks refetch on PUSH instead of on a fixed
// timer. Migrated pages can then relax their `refetchInterval` to a slow
// safety-net value rather than polling every few seconds.
//
// EventSource cannot send the `Authorization` header, so — exactly like
// `api/llm.ts` — the stream is consumed via fetch() + a ReadableStream reader
// parsing `data: <json>` frames. The connection auto-reconnects with capped
// exponential backoff when it drops.

export interface JobEvent {
  kind: string
  id: string
  status: string
  ts?: number
  node_id?: string
  rc?: number
}

export interface UseJobEventStreamOptions {
  /** When false, the stream is not opened (e.g. before a job exists). */
  enabled?: boolean
  /** Optional extra handler invoked for every event, after cache invalidation. */
  onEvent?: (event: JobEvent) => void
}

const STREAM_URL = '/api/v1/events/jobs/stream'
const BASE_BACKOFF_MS = 1_000
const MAX_BACKOFF_MS = 30_000

/**
 * Map a job event to the React Query keys that should be invalidated. Kept as a
 * pure function so the mapping is unit-testable without a live QueryClient.
 */
export function queryKeysForEvent(event: JobEvent): QueryKey[] {
  const keys: QueryKey[] = []
  if (event.kind === 'ansible_job') {
    keys.push(['ansible-job', event.id])
    if (event.node_id) {
      keys.push(['ansible-jobs-node', event.node_id])
      keys.push(['executions-node', event.node_id])
    }
  } else if (event.kind === 'bootstrap') {
    keys.push(['bootstrap-status', event.id])
    keys.push(['bootstrap-logs', event.id])
    keys.push(['node', event.id])
    keys.push(['nodes'])
    keys.push(['fleet-overview'])
  }
  return keys
}

/**
 * Parse a single SSE frame (the text between two `\n\n` separators) into a
 * JobEvent, or null when the frame is a comment/keepalive/malformed. Exported
 * for unit testing of the wire parser.
 */
export function parseEventFrame(frame: string): JobEvent | null {
  const line = frame.split('\n').find((l) => l.startsWith('data:'))
  if (!line) return null
  const payload = line.replace(/^data:\s*/, '')
  if (!payload || payload === '[DONE]') return null
  try {
    const ev = JSON.parse(payload) as JobEvent
    if (ev && typeof ev.kind === 'string' && typeof ev.id === 'string') return ev
    return null
  } catch {
    return null
  }
}

/**
 * Open the job-event SSE stream and invalidate affected queries on each push.
 * Mount this once anywhere that benefits from live job-state updates.
 */
export function useJobEventStream(options: UseJobEventStreamOptions = {}): void {
  const { enabled = true, onEvent } = options
  const qc = useQueryClient()

  // Keep the latest onEvent without retriggering the connection effect.
  const onEventRef = useRef(onEvent)
  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (!enabled) return

    let stopped = false
    let controller: AbortController | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let backoff = BASE_BACKOFF_MS

    const handleEvent = (ev: JobEvent) => {
      for (const key of queryKeysForEvent(ev)) {
        void qc.invalidateQueries({ queryKey: key })
      }
      onEventRef.current?.(ev)
    }

    const connect = async () => {
      controller = new AbortController()
      const token = getAccessToken() || ''
      const res = await fetch(STREAM_URL, {
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: controller.signal,
      })
      if (!res.ok || !res.body) {
        throw new Error(`job-event stream failed: ${res.status}`)
      }
      // Connection established — reset backoff so the next drop retries quickly.
      backoff = BASE_BACKOFF_MS

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
          const ev = parseEventFrame(frame)
          if (ev) handleEvent(ev)
          sep = buffer.indexOf('\n\n')
        }
      }
    }

    const run = () => {
      connect()
        .catch(() => {
          // Swallow — a reconnect is scheduled in finally(). Aborts on unmount
          // also land here and are filtered out by the `stopped` guard.
        })
        .finally(() => {
          if (stopped) return
          reconnectTimer = setTimeout(run, backoff)
          backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
        })
    }

    run()

    return () => {
      stopped = true
      controller?.abort()
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [enabled, qc])
}
