import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'

export function FleetDashboard() {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')

  const { data: overview, isLoading: ovLoading } = useQuery({
    queryKey: ['fleet-overview'],
    queryFn: fleetApi.overview,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  const {
    data: nodes,
    isLoading: nodesLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['nodes', page, statusFilter],
    queryFn: () => fleetApi.nodes({ page, per_page: 50, status: statusFilter || undefined }),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>

      {ovLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : overview ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Nodes', value: overview.total_nodes, colour: 'text-gray-900' },
            { label: 'Online', value: overview.online, colour: 'text-green-600' },
            { label: 'Offline / Stale', value: overview.offline + overview.stale, colour: 'text-red-600' },
            { label: 'Avg Drift Score', value: overview.avg_drift_score, colour: 'text-brand-600' },
          ].map(({ label, value, colour }) => (
            <div key={label} className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
              <p className={`text-3xl font-bold mt-1 ${colour}`}>{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Status:</label>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="text-sm border border-gray-300 rounded px-2 py-1"
        >
          <option value="">All</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="stale">Stale</option>
          <option value="unknown">Unknown</option>
        </select>
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {nodesLoading ? (
          <Skeleton rows={10} />
        ) : isError ? (
          <ErrorState message="Failed to load nodes" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">OS</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">Last Seen</th>
                  <th className="px-4 py-3">Tags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {nodes?.items.map((node) => (
                  <tr key={node.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-medium">
                      <Link to={`/nodes/${node.id}`} className="text-brand-600 hover:underline">
                        {node.hostname ?? node.minion_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={node.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-600">{node.os_version ?? '—'}</td>
                    <td className="px-4 py-3">
                      <DriftBadge score={node.drift_score} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {node.last_seen_at
                        ? formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {node.tags.map((t) => (
                          <span
                            key={t.key}
                            className="text-xs bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded"
                          >
                            {t.key}={t.value}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {nodes && (
              <Pagination
                page={page}
                total={nodes.total}
                perPage={nodes.per_page}
                onPage={setPage}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}
