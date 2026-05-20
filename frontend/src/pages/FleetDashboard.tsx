import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { BootstrapModal } from './BootstrapModal'
import { formatDistanceToNow } from 'date-fns'

export function FleetDashboard() {
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(50)
  const [statusFilter, setStatusFilter] = useState('')
  const [showBootstrap, setShowBootstrap] = useState(false)

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
    queryKey: ['nodes', page, perPage, statusFilter],
    queryFn: () => fleetApi.nodes({ page, per_page: perPage, status: statusFilter || undefined }),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>
        <button
          onClick={() => setShowBootstrap(true)}
          className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
        >
          + Bootstrap Node
        </button>
      </div>

      {/* Stat cards */}
      {ovLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : overview ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Nodes',    value: overview.total_nodes,                    accent: 'border-l-brand-600',   num: 'text-gray-900' },
            { label: 'Online',         value: overview.online,                         accent: 'border-l-emerald-500', num: 'text-emerald-700' },
            { label: 'Offline / Stale',value: overview.offline + overview.stale,       accent: 'border-l-red-500',     num: 'text-red-700' },
            { label: 'Avg Drift Score',value: overview.avg_drift_score,                accent: 'border-l-amber-500',   num: 'text-amber-700' },
          ].map(({ label, value, accent, num }) => (
            <div key={label} className={`bg-white rounded-xl border border-gray-200 border-l-4 ${accent} p-5 shadow-sm`}>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">{label}</p>
              <p className={`text-4xl font-bold tabular-nums ${num}`}>{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      {/* Filter */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-gray-600">Status:</label>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="text-sm bg-white border border-gray-300 text-gray-900 rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-600"
        >
          <option value="">All</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="stale">Stale</option>
          <option value="unknown">Unknown</option>
        </select>
      </div>

      {/* Node table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {nodesLoading ? (
          <Skeleton rows={10} />
        ) : isError ? (
          <ErrorState message="Failed to load nodes" retry={refetch} />
        ) : (
          <>
            {nodes?.items.length === 0 ? (
              <div className="px-4 py-16 text-center space-y-4">
                <p className="text-4xl">🖥️</p>
                <p className="text-lg font-semibold text-gray-700">No nodes in your fleet yet</p>
                <p className="text-sm text-gray-500 max-w-sm mx-auto">
                  Bootstrap a Mac Mini to get started. Make sure Remote Login (SSH) is enabled on the device first.
                </p>
                <button
                  onClick={() => setShowBootstrap(true)}
                  className="px-6 py-2.5 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
                >
                  Bootstrap your first node →
                </button>
              </div>
            ) : (
              <>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
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
                        <td className="px-4 py-3 font-medium font-mono text-xs">
                          <Link to={`/nodes/${node.id}`} className="text-brand-600 hover:text-brand-700 hover:underline">
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
                              <span key={t.key} className="text-xs bg-brand-50 text-brand-700 border border-brand-200 px-1.5 py-0.5 rounded">
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
                  <Pagination page={page} total={nodes.total} perPage={nodes.per_page} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1) }} />
                )}
              </>
            )}
          </>
        )}
      </div>
      {showBootstrap && <BootstrapModal onClose={() => setShowBootstrap(false)} />}
    </div>
  )
}
