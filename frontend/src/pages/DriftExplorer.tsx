import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { driftApi } from '../api/drift'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'
import { useFilterStore } from '../stores/filterStore'

const SEVERITIES = ['', 'clean', 'low', 'medium', 'high', 'critical']

export function DriftExplorer() {
  const [page, setPage] = useState(1)
  const { driftSeverity, setDriftSeverity } = useFilterStore()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['drift', driftSeverity, page],
    queryFn: () => driftApi.list({ severity: driftSeverity || undefined, page, per_page: 50 }),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Drift Explorer</h1>
        <Link
          to="/drift/compare"
          className="px-3 py-1.5 text-sm bg-brand-600 text-white rounded hover:bg-brand-700 flex items-center gap-1.5"
        >
          Compare nodes →
        </Link>
      </div>
      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Severity:</label>
        <select
          value={driftSeverity}
          onChange={(e) => { setDriftSeverity(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1"
        >
          {SEVERITIES.map((s) => <option key={s} value={s}>{s || 'All'}</option>)}
        </select>
        {data && <span className="text-sm text-gray-500">{data.total} nodes</span>}
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? <Skeleton rows={10} /> : isError ? (
          <ErrorState message="Failed to load drift data" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Drift Score</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Baseline</th>
                  <th className="px-4 py-3">Computed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((d) => (
                  <tr key={d.node_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">
                      <Link to={`/nodes/${d.node_id}`} className="text-brand-600 hover:underline">
                        {d.hostname ?? d.node_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3"><DriftBadge score={d.drift_score} /></td>
                    <td className="px-4 py-3 capitalize text-gray-600">{d.severity}</td>
                    <td className="px-4 py-3 text-gray-600">{d.baseline_name ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {d.computed_at ? formatDistanceToNow(new Date(d.computed_at), { addSuffix: true }) : '—'}
                    </td>
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
