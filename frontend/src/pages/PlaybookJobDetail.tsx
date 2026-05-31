import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { playbooksApi, type AnsibleJob } from '../api/playbooks'
import { formatDistanceToNow, formatDuration, intervalToDuration } from 'date-fns'

function statusBadge(status: string) {
  const cls =
    status === 'completed' ? 'bg-green-100 text-green-800' :
    status === 'failed'    ? 'bg-red-100 text-red-800' :
    status === 'running'   ? 'bg-blue-100 text-blue-800 animate-pulse' :
    'bg-gray-100 text-gray-700'
  return <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls}`}>{status}</span>
}

function jobDuration(job: AnsibleJob): string {
  if (!job.started_at || !job.completed_at) return '—'
  const d = intervalToDuration({ start: new Date(job.started_at), end: new Date(job.completed_at) })
  return formatDuration(d, { format: ['minutes', 'seconds'] }) || '<1s'
}

export function PlaybookJobDetail() {
  const { jobId } = useParams<{ jobId: string }>()

  const { data: job, isLoading, isError } = useQuery({
    queryKey: ['ansible-job', jobId],
    queryFn: () => playbooksApi.getJob(jobId!),
    enabled: !!jobId,
    // Poll while running so logs update in real time
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'running' || s === 'pending' ? 3000 : false
    },
  })

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

  const isLive = job.status === 'running' || job.status === 'pending'

  return (
    <div className="space-y-6 max-w-5xl">
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
                <span className="text-xs text-blue-600 font-medium animate-pulse">● live</span>
              )}
            </div>
            <p className="text-sm text-gray-500">
              Target: <span className="font-medium text-gray-700">{job.target_label || job.target_type}</span>
              {job.triggered_by && (
                <span className="ml-3">Triggered by: <span className="font-medium text-gray-700">{job.triggered_by}</span></span>
              )}
            </p>
          </div>
          <div className="text-right text-sm text-gray-500 shrink-0 space-y-0.5">
            {job.started_at && (
              <p>{formatDistanceToNow(new Date(job.started_at), { addSuffix: true })}</p>
            )}
            <p className="font-mono">{jobDuration(job)}</p>
            {typeof job.rc === 'number' && (
              <p className="font-mono">
                Exit: <span className={job.rc === 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>{job.rc}</span>
              </p>
            )}
          </div>
        </div>

        {/* Extra vars */}
        {job.extravars && Object.keys(job.extravars).length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Extra Vars</p>
            <pre className="text-xs bg-gray-50 border border-gray-100 rounded p-3 font-mono text-gray-700 overflow-x-auto">
              {JSON.stringify(job.extravars, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Logs */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 bg-gray-50">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Output</p>
          {isLive && (
            <span className="text-xs text-blue-500">Polling every 3s…</span>
          )}
        </div>
        {job.stdout ? (
          <pre
            className="text-xs font-mono bg-gray-950 text-green-300 p-4 overflow-auto leading-relaxed whitespace-pre-wrap"
            style={{ minHeight: '400px', maxHeight: '70vh' }}
          >
            {job.stdout}
          </pre>
        ) : (
          <div className="flex items-center justify-center bg-gray-950" style={{ minHeight: '200px' }}>
            {isLive ? (
              <div className="text-center space-y-2">
                <div className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mx-auto" />
                <p className="text-xs text-gray-500">Waiting for output…</p>
              </div>
            ) : (
              <p className="text-xs text-gray-500">No output recorded</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
