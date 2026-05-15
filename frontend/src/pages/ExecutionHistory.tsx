import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { executionsApi } from '../api/executions'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow, formatDuration, intervalToDuration } from 'date-fns'
import { useFilterStore } from '../stores/filterStore'

const STATUSES = ['', 'pending', 'running', 'completed', 'failed']

function jobDuration(job: { started_at: string | null; completed_at: string | null }): string {
  if (!job.started_at || !job.completed_at) return '—'
  const duration = intervalToDuration({ start: new Date(job.started_at), end: new Date(job.completed_at) })
  return formatDuration(duration, { format: ['minutes', 'seconds'] }) || '<1s'
}

export function ExecutionHistory() {
  const [page, setPage] = useState(1)
  const { executionStatus, setExecutionStatus } = useFilterStore()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['executions', executionStatus, page],
    queryFn: () => executionsApi.list({ status: executionStatus || undefined, page, per_page: 25 }),
    staleTime: 10_000,
    refetchInterval: 15_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Execution History</h1>
      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Status:</label>
        <select value={executionStatus} onChange={(e) => { setExecutionStatus(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1">
          {STATUSES.map((s) => <option key={s} value={s}>{s || 'All'}</option>)}
        </select>
        {data && <span className="text-sm text-gray-500">{data.total} jobs</span>}
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? <Skeleton rows={8} /> : isError ? (
          <ErrorState message="Failed to load executions" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Target</th>
                  <th className="px-4 py-3">Triggered By</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((j) => (
                  <tr key={j.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link to={`/executions/${j.id}`} className="text-brand-600 hover:underline font-mono text-xs">{j.type}</Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        j.status === 'completed' ? 'bg-green-100 text-green-800' :
                        j.status === 'failed' ? 'bg-red-100 text-red-800' :
                        j.status === 'running' ? 'bg-blue-100 text-blue-800' :
                        'bg-gray-100 text-gray-700'
                      }`}>{j.status}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs font-mono">
                      {j.target_type}{j.target_id ? `:${j.target_id.slice(0, 8)}` : ''}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{j.triggered_by}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {j.started_at ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true }) : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">{jobDuration(j)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && <Pagination page={page} total={data.total} perPage={data.per_page} onPage={setPage} />}
          </>
        )}
      </div>
    </div>
  )
}
