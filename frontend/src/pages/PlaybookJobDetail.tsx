import { useParams, Link } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { playbooksApi, type AnsibleJob } from '../api/playbooks'
import { PlaybookRunModal } from './PlaybookRunModal'
import { LogPane } from '../lib/LogPane'
import { formatDistanceToNow, formatDuration, intervalToDuration } from 'date-fns'
import { formatIST } from '../utils/time'

function statusBadge(status: string) {
  const cls =
    status === 'completed'  ? 'bg-green-100 text-green-800' :
    status === 'failed'     ? 'bg-red-100 text-red-800' :
    status === 'running'    ? 'bg-blue-100 text-blue-800 animate-pulse' :
    status === 'cancelled'  ? 'bg-amber-100 text-amber-800' :
    'bg-gray-100 text-gray-700'
  return <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls}`}>{status}</span>
}

function jobDuration(job: AnsibleJob): string {
  if (!job.started_at || !job.completed_at) return '—'
  const d = intervalToDuration({ start: new Date(job.started_at), end: new Date(job.completed_at) })
  return formatDuration(d, { format: ['minutes', 'seconds'] }) || '<1s'
}

const SENSITIVE_KEY = /password|secret|token|api_key|apikey|passphrase/i

function maskExtravars(extravars: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(extravars).map(([k, v]) => [
      k,
      SENSITIVE_KEY.test(k) ? '••••••••' : v,
    ])
  )
}

function buildRerunVars(extravars: Record<string, unknown>): Record<string, string> {
  // Pre-fill all vars including sensitive ones — they render masked (type=password).
  // User can change any value before submitting.
  return Object.fromEntries(
    Object.entries(extravars).map(([k, v]) => [k, String(v ?? '')])
  )
}

export function PlaybookJobDetail() {
  const { jobId } = useParams<{ jobId: string }>()

  // Delta-accumulator for log text (#371): accumulates deltas so only new bytes transfer.
  const acc = useRef<{ text: string; total: number }>({ text: '', total: 0 })
  const [logText, setLogText] = useState('')

  // Reset accumulator when jobId changes (navigation between jobs).
  useEffect(() => {
    acc.current = { text: '', total: 0 }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional reset when navigating to a different job
    setLogText('')
  }, [jobId])

  const { data: job, isLoading, isError } = useQuery({
    queryKey: ['ansible-job', jobId],
    queryFn: () => playbooksApi.getJob(jobId!, acc.current.total),
    enabled: !!jobId,
    // Poll while running so logs update in real time
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'running' || s === 'pending' ? 3000 : false
    },
  })

  // Delta accumulation: append new bytes on each response (#371).
  useEffect(() => {
    if (!job) return
    if (job.stdout_total_len == null) {
      // Old server (no delta support): fall back to full replacement
      acc.current = { text: job.stdout ?? '', total: 0 }
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing accumulated log from polled server response (#371 delta accumulator)
      setLogText(job.stdout ?? '')
    } else if (job.stdout_total_len < acc.current.total) {
      // stdout was rewritten (error path resync): reset and re-poll from byte 0
      acc.current = { text: '', total: 0 }
      setLogText('')
    } else {
      // Normal delta: append new bytes
      const appended = acc.current.text + (job.stdout ?? '')
      acc.current = { text: appended, total: job.stdout_total_len }
      setLogText(appended)
    }
  }, [job])

  // Log scroll/tail-follow is handled by the shared LogPane component (#373).

  // Hooks must be declared before any early returns (Rules of Hooks)
  const qc = useQueryClient()
  const cancelMutation = useMutation({
    mutationFn: () => playbooksApi.cancel(jobId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ansible-job', jobId] })
    },
  })

  const [showRerun, setShowRerun] = useState(false)

  const { data: allPlaybooks } = useQuery({
    queryKey: ['playbooks-for-rerun'],
    queryFn: () => playbooksApi.list(),
    staleTime: 60_000,
    enabled: showRerun,
  })
  const rerunEntry = allPlaybooks?.find(p => p.filename === job?.playbook)

  const isLive = job?.status === 'running' || job?.status === 'pending'
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting elapsed timer when job leaves live state; interval drives updates
    if (!isLive || !job?.started_at) { setElapsed(0); return }
    const base = new Date(job.started_at).getTime()
    const tick = () => setElapsed(Math.floor((Date.now() - base) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [isLive, job?.started_at])

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-sm text-gray-400">
      Loading job…
    </div>
  )

  if (isError || !job) return (
    <div className="space-y-4">
      <Link to="/automation?tab=executions" className="text-sm text-brand-600 hover:underline">← Executions</Link>
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
        Job not found or failed to load.
      </div>
    </div>
  )

  function fmtElapsed(s: number): string {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return m > 0 ? `${m}m ${sec}s elapsed` : `${sec}s elapsed`
  }

  return (
    <div className="flex flex-col max-w-7xl h-[calc(100vh-80px)]">
      <div className="flex items-center gap-3">
        <Link to="/automation?tab=executions" className="text-sm text-brand-600 hover:underline">← Executions</Link>
        <span className="text-gray-300">/</span>
        <span className="text-sm font-mono text-gray-600">{job.playbook}</span>
      </div>

      {/* Header card */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-bold text-gray-900 font-mono">{job.playbook}</h1>
              {statusBadge(job.status)}
              {isLive && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-blue-600 font-medium animate-pulse">● live</span>
                  {elapsed > 0 && (
                    <span className="text-xs text-gray-400 font-mono">{fmtElapsed(elapsed)}</span>
                  )}
                </div>
              )}
            </div>
            <p className="text-sm text-gray-500">
              Target: <span className="font-medium text-gray-700">{job.target_label || job.target_type}</span>
              {job.triggered_by && (
                <span className="ml-3">Triggered by: <span className="font-medium text-gray-700">{job.triggered_by}</span></span>
              )}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            {isLive && (
              <button
                onClick={() => {
                  if (window.confirm('Cancel this playbook run? This will send SIGTERM to the Ansible process.')) {
                    cancelMutation.mutate()
                  }
                }}
                disabled={cancelMutation.isPending}
                className="px-3 py-1.5 text-sm font-medium bg-white border border-red-300 text-red-600 rounded-lg hover:bg-red-50 flex items-center gap-1.5 shrink-0 disabled:opacity-50"
              >
                {cancelMutation.isPending ? (
                  <>
                    <span className="w-3 h-3 border border-red-400 border-t-transparent rounded-full animate-spin" />
                    Cancelling…
                  </>
                ) : (
                  <>
                    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    Cancel
                  </>
                )}
              </button>
            )}
            {(job.status === 'completed' || job.status === 'failed') && (
              <button
                onClick={() => setShowRerun(true)}
                className="px-3 py-1.5 text-sm font-medium bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 flex items-center gap-1.5 shrink-0"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Re-run
              </button>
            )}
            <div className="text-right text-sm text-gray-500 space-y-0.5">
              {job.started_at && (
                <p title={formatIST(job.started_at)}>{formatDistanceToNow(new Date(job.started_at), { addSuffix: true })}</p>
              )}
              <p className="font-mono">{jobDuration(job)}</p>
              {typeof job.rc === 'number' && (
                <p className="font-mono">
                  Exit: <span className={job.rc === 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>{job.rc}</span>
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Command being run */}
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Command</p>
          <pre className="text-xs bg-gray-950 text-green-300 border border-gray-800 rounded p-3 font-mono overflow-x-auto whitespace-pre-wrap">
            {(() => {
              const masked = maskExtravars(job.extravars || {})
              const eFlags = Object.entries(masked)
                .map(([k, v]) => `-e ${k}='${v}'`)
                .join(' ')
              const vFlag = job.verbosity && job.verbosity > 0 ? ' -' + 'v'.repeat(job.verbosity) : ''
              return `ansible-playbook ${job.playbook}`
                + ` --limit ${job.target_label ?? job.target_id}`
                + (eFlags ? ` ${eFlags}` : '')
                + vFlag
            })()}
          </pre>
        </div>

        {/* Extra vars */}
        {job.extravars && Object.keys(job.extravars).length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Extra Vars</p>
            <pre className="text-xs bg-gray-50 border border-gray-100 rounded p-3 font-mono text-gray-700 overflow-x-auto">
              {JSON.stringify(maskExtravars(job.extravars), null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Logs */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 bg-gray-50">
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Output</p>
            {(() => {
              // Prefer server-extracted running_task; fall back to regex on accumulated logText for old servers
              const taskName = job?.running_task ?? logText.match(/\[running: ([^\]]+)\]\s*$/)?.[1]
              return taskName ? (
                <p className="text-xs text-amber-600 mt-0.5 font-mono">▶ {taskName}</p>
              ) : null
            })()}
          </div>
          {isLive && (
            <span className="text-xs text-blue-500">Polling every 3s…</span>
          )}
        </div>
        <LogPane raw={logText} isLive={isLive} emptyText="No output recorded" />
      </div>

      {/* Re-run modal */}
      {showRerun && rerunEntry && (
        <PlaybookRunModal
          playbook={rerunEntry}
          onClose={() => setShowRerun(false)}
          initialTargetType={job.target_type as 'node' | 'group'}
          initialTargetId={job.target_id ?? undefined}
          initialVars={buildRerunVars(job.extravars ?? {})}
          initialTimeout={job.timeout_seconds}
        />
      )}
      {showRerun && !rerunEntry && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 text-sm text-gray-600">
            Loading playbook details…
          </div>
        </div>
      )}
    </div>
  )
}
