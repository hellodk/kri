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
      <h1 className="text-2xl font-bold text-white">Fleet Dashboard</h1>

      {ovLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-28 rounded-xl animate-pulse" style={{ background: '#1a1a3e' }} />
          ))}
        </div>
      ) : overview ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Nodes', value: overview.total_nodes, colour: 'text-white',         border: 'border-l-brand-500',   glow: 'shadow-brand-500/10' },
            { label: 'Online',      value: overview.online,       colour: 'text-emerald-400',   border: 'border-l-emerald-500', glow: 'shadow-emerald-500/10' },
            { label: 'Offline / Stale', value: overview.offline + overview.stale, colour: 'text-red-400', border: 'border-l-red-500', glow: 'shadow-red-500/10' },
            { label: 'Avg Drift',   value: overview.avg_drift_score, colour: 'text-amber-400', border: 'border-l-amber-500',   glow: 'shadow-amber-500/10' },
          ].map(({ label, value, colour, border, glow }) => (
            <div key={label} className={`rounded-xl border border-white/8 border-l-4 ${border} p-5 shadow-lg ${glow}`}
                 style={{ background: 'linear-gradient(135deg, #1a1a3e 0%, #13132e 100%)' }}>
              <p className="text-white/40 text-xs font-medium uppercase tracking-wider mb-2">{label}</p>
              <p className={`text-4xl font-bold tabular-nums ${colour}`}>{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex items-center gap-3">
        <label className="text-sm text-white/40">Status:</label>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="text-sm bg-white/5 border border-white/10 text-white rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-500"
        >
          <option value="">All</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="stale">Stale</option>
          <option value="unknown">Unknown</option>
        </select>
      </div>

      <div className="rounded-xl border border-white/8 overflow-hidden" style={{ background: '#13132e' }}>
        {nodesLoading ? (
          <Skeleton rows={10} />
        ) : isError ? (
          <ErrorState message="Failed to load nodes" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/8 text-left text-xs text-white/30 uppercase tracking-wider" style={{ background: '#1a1a3e' }}>
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">OS</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">Last Seen</th>
                  <th className="px-4 py-3">Tags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {nodes?.items.map((node) => (
                  <tr key={node.id} className="hover:bg-white/3 transition-colors">
                    <td className="px-4 py-3 font-medium font-mono text-xs">
                      <Link to={`/nodes/${node.id}`} className="text-brand-400 hover:text-brand-300 transition-colors">
                        {node.hostname ?? node.minion_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={node.status} />
                    </td>
                    <td className="px-4 py-3 text-white/40 text-xs">{node.os_version ?? '—'}</td>
                    <td className="px-4 py-3">
                      <DriftBadge score={node.drift_score} />
                    </td>
                    <td className="px-4 py-3 text-white/30 text-xs">
                      {node.last_seen_at
                        ? formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {node.tags.map((t) => (
                          <span
                            key={t.key}
                            className="text-xs bg-brand-950/50 text-brand-300 border border-brand-800/40 px-1.5 py-0.5 rounded-full"
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
