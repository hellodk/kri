import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { executionsApi } from '../api/executions'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { formatLocalDateTime, formatLocalTime } from '../utils/time'
import { useJobEventStream } from '../hooks/useJobEventStream'

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()

  // salt_job events are pushed over SSE (#921); the hook invalidates ['job', jobId]
  // on push so this query refetches immediately when a new salt execution lands.
  // The slow 30s safety-net poll covers the gap when the SSE stream is offline.
  useJobEventStream({ enabled: !!jobId })

  const { data: job, isLoading: jLoading, isError: jError } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => executionsApi.get(jobId!),
    enabled: !!jobId,
    staleTime: 10_000,
    refetchInterval: 30_000,
  })

  const { data: results, isLoading: rLoading } = useQuery({
    queryKey: ['job-results', jobId],
    queryFn: () => executionsApi.results(jobId!, { per_page: 100 }),
    enabled: !!jobId && job?.status !== 'pending',
    staleTime: 10_000,
  })

  if (jLoading) return <Skeleton rows={4} />
  if (jError || !job) return <ErrorState message="Job not found" />

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/executions" className="text-sm text-brand-600 hover:underline">← Executions</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900 font-mono">{job.type}</h1>
        <span className={`text-xs px-2 py-0.5 rounded ${
          job.status === 'completed' ? 'bg-green-100 text-green-800' :
          job.status === 'failed' ? 'bg-red-100 text-red-800' :
          job.status === 'running' ? 'bg-blue-100 text-blue-800' :
          'bg-gray-100 text-gray-700'
        }`}>{job.status}</span>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        {(
          [
            ['Salt JID', job.salt_jid ?? '—'],
            ['Target', `${job.target_type}${job.target_id ? ':' + job.target_id.slice(0, 8) : ''}`],
            ['Triggered By', job.triggered_by],
            ['Started', job.started_at ? formatLocalDateTime(job.started_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'],
            ['Completed', job.completed_at ? formatLocalDateTime(job.completed_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'],
          ] as [string, string][]
        ).map(([label, value]) => (
          <div key={label}>
            <p className="text-gray-500 text-xs">{label}</p>
            <p className="font-medium mt-0.5 truncate">{value}</p>
          </div>
        ))}
      </div>
      {rLoading ? <Skeleton rows={4} /> : results && results.items.length > 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 text-sm font-medium text-gray-700">
            Results ({results.total})
          </div>
          <div className="divide-y divide-gray-100">
            {results.items.map((r) => (
              <details key={r.id} className="group">
                <summary className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 text-sm">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${r.exit_code === 0 ? 'bg-green-500' : 'bg-red-500'}`} />
                  <span className="font-mono text-xs text-gray-500">{r.node_id.slice(0, 8)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${r.exit_code === 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    exit {r.exit_code ?? '?'}
                  </span>
                  <span className="ml-auto text-xs text-gray-400">
                    {formatLocalTime(r.completed_at)}
                  </span>
                </summary>
                {(r.stdout || r.stderr) && (
                  <div className="px-4 pb-3 space-y-2">
                    {r.stdout && (
                      <pre className="text-xs bg-gray-50 rounded p-2 overflow-auto max-h-40 font-mono whitespace-pre-wrap">{r.stdout}</pre>
                    )}
                    {r.stderr && (
                      <pre className="text-xs bg-red-50 text-red-700 rounded p-2 overflow-auto max-h-40 font-mono whitespace-pre-wrap">{r.stderr}</pre>
                    )}
                  </div>
                )}
              </details>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
