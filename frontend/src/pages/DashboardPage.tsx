import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { fleetApi } from '../api/fleet'
import { saltKeysApi } from '../api/saltKeys'
import { formatRelative, formatDate } from '../utils/dateFormat'
import type { Paginated, Node } from '../types'

interface SecurityDashboard {
  vulnerabilities: { critical: number; high: number; medium: number; low: number }
  total_vulnerabilities: number
  nodes_with_critical_or_high: number
}

interface DriftSummaryItem {
  node_id: string
  hostname: string | null
  drift_score: number
  computed_at: string | null
}

// ── Card component ─────────────────────────────────────────────────────────────

type CardVariant = 'green' | 'amber' | 'red' | 'neutral'

const CARD_STYLES: Record<CardVariant, { border: string; bg: string; label: string; num: string }> = {
  green:   { border: 'border-l-emerald-500', bg: 'bg-emerald-50', label: 'text-emerald-700', num: 'text-emerald-700' },
  amber:   { border: 'border-l-amber-500',   bg: 'bg-amber-50',   label: 'text-amber-700',   num: 'text-amber-700'   },
  red:     { border: 'border-l-red-500',      bg: 'bg-red-50',     label: 'text-red-700',     num: 'text-red-700'     },
  neutral: { border: 'border-l-brand-600',    bg: 'bg-white',      label: 'text-gray-500',    num: 'text-gray-900'    },
}

function SummaryCard({
  title, to, variant = 'neutral', children,
}: {
  title: string
  to: string
  variant?: CardVariant
  children: React.ReactNode
}) {
  const s = CARD_STYLES[variant]
  return (
    <Link
      to={to}
      className={`block rounded-xl border border-gray-200 border-l-4 ${s.border} ${s.bg} p-5 shadow-sm hover:shadow-md transition-shadow`}
    >
      <p className={`text-xs font-semibold uppercase tracking-wide mb-2 ${s.label}`}>{title}</p>
      {children}
    </Link>
  )
}

// ── Main dashboard ─────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { data: overview } = useQuery({
    queryKey: ['fleet-overview'],
    queryFn: fleetApi.overview,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  const { data: nodesData } = useQuery({
    queryKey: ['dashboard-nodes'],
    queryFn: () => fleetApi.nodes({ page: 1, per_page: 50, sort: 'drift_score:desc' }),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const { data: security } = useQuery({
    queryKey: ['security-dashboard'],
    queryFn: () => api.get<SecurityDashboard>('/api/v1/security/dashboard'),
    staleTime: 60_000,
    refetchInterval: 30_000,
  })

  const { data: saltKeys } = useQuery({
    queryKey: ['salt-keys'],
    queryFn: () => saltKeysApi.list(),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const { data: driftData } = useQuery({
    queryKey: ['dashboard-drift'],
    queryFn: () => api.get<Paginated<DriftSummaryItem>>('/api/v1/drift?sort=drift_score:desc&per_page=5'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  // Compute node counts
  const nodes: Node[] = nodesData?.items ?? []
  const onlineCount = overview?.online ?? 0
  const offlineCount = (overview?.offline ?? 0) + (overview?.stale ?? 0)
  const maintCount = nodes.filter((n) => n.maintenance_mode).length

  // Security variant
  const criticalCount = security?.vulnerabilities?.critical ?? 0
  const highCount = security?.vulnerabilities?.high ?? 0
  const secVariant: CardVariant = criticalCount > 0 ? 'red' : highCount > 0 ? 'amber' : 'green'

  // Drift variant
  const avgDrift = overview?.avg_drift_score ?? 0
  const driftedCount = (overview?.nodes_medium ?? 0) + (overview?.nodes_high ?? 0) + (overview?.nodes_critical ?? 0)
  const driftVariant: CardVariant = driftedCount === 0 ? 'green' : avgDrift > 50 ? 'red' : 'amber'

  // Keys variant
  const pendingKeys = saltKeys?.pending_count ?? 0
  const keysVariant: CardVariant = pendingKeys > 0 ? 'amber' : 'green'

  // Nodes variant
  const nodesVariant: CardVariant = offlineCount > 0 ? 'amber' : 'green'

  // Most drifted nodes (top 5 with drift > 0)
  const topDrifted = (driftData?.items ?? []).filter((d) => d.drift_score > 0).slice(0, 5)

  // Recent activity — recent bootstrap runs across all nodes from node list
  // We show nodes with recent last_seen_at as a proxy for recent activity
  const recentActivity = [...nodes]
    .filter((n) => n.last_seen_at)
    .sort((a, b) => new Date(b.last_seen_at!).getTime() - new Date(a.last_seen_at!).getTime())
    .slice(0, 6)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Fleet-wide overview. Refreshes every 30 seconds.</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Nodes card */}
        <SummaryCard title="Nodes" to="/fleet" variant={nodesVariant}>
          <p className="text-3xl font-bold tabular-nums text-gray-900 mb-2">
            {overview?.total_nodes ?? '—'}
          </p>
          <div className="space-y-0.5 text-xs">
            <p className="text-emerald-600 font-medium">{onlineCount} online</p>
            {offlineCount > 0 && <p className="text-red-600">{offlineCount} offline/stale</p>}
            {maintCount > 0 && <p className="text-amber-600">{maintCount} in maintenance</p>}
          </div>
        </SummaryCard>

        {/* Drift card */}
        <SummaryCard title="Drift" to="/drift" variant={driftVariant}>
          <p className="text-3xl font-bold tabular-nums text-gray-900 mb-2">
            {driftedCount}
          </p>
          <div className="space-y-0.5 text-xs">
            <p className="text-gray-600">drifted nodes</p>
            <p className="text-gray-500">avg score: {avgDrift}</p>
          </div>
        </SummaryCard>

        {/* Security card */}
        <SummaryCard title="Security" to="/security" variant={secVariant}>
          <p className="text-3xl font-bold tabular-nums text-gray-900 mb-2">
            {criticalCount}
          </p>
          <div className="space-y-0.5 text-xs">
            <p className="text-red-600">{criticalCount} critical CVEs</p>
            <p className="text-amber-600">{highCount} high CVEs</p>
          </div>
        </SummaryCard>

        {/* Salt Keys card */}
        <SummaryCard title="Minion Keys" to="/salt-keys" variant={keysVariant}>
          <p className="text-3xl font-bold tabular-nums text-gray-900 mb-2">
            {pendingKeys}
          </p>
          <div className="space-y-0.5 text-xs">
            <p className={pendingKeys > 0 ? 'text-amber-600 font-medium' : 'text-gray-500'}>
              {pendingKeys > 0 ? `${pendingKeys} pending approval` : 'no pending keys'}
            </p>
          </div>
        </SummaryCard>
      </div>

      {/* Two-column lists */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Most drifted nodes */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800">Most Drifted Nodes</h2>
            <Link to="/drift" className="text-xs text-brand-600 hover:underline font-medium">
              View all →
            </Link>
          </div>
          {topDrifted.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">
              {driftData ? 'All nodes in compliance' : 'Loading…'}
            </div>
          ) : (
            <ul className="divide-y divide-gray-50">
              {topDrifted.map((d) => {
                const scoreVariant =
                  d.drift_score >= 81 ? 'bg-red-100 text-red-700' :
                  d.drift_score >= 51 ? 'bg-orange-100 text-orange-700' :
                  d.drift_score >= 21 ? 'bg-amber-100 text-amber-700' :
                  'bg-gray-100 text-gray-600'

                // Try to match with node for link
                const node = nodes.find((n) => n.id === d.node_id)
                const displayName = d.hostname ?? d.node_id.slice(0, 8)

                return (
                  <li key={d.node_id} className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50 transition-colors">
                    {node ? (
                      <Link to={`/nodes/${d.node_id}`} className="flex-1 text-sm font-mono font-medium text-brand-600 hover:underline">
                        {displayName}
                      </Link>
                    ) : (
                      <span className="flex-1 text-sm font-mono font-medium text-gray-700">{displayName}</span>
                    )}
                    <span className={`text-xs px-2 py-0.5 rounded font-semibold tabular-nums ${scoreVariant}`}>
                      {d.drift_score}
                    </span>
                    {d.computed_at && (
                      <span className="text-xs text-gray-400 shrink-0">
                        {formatDate(d.computed_at, 'MM/dd')}
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {/* Recent activity */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800">Recent Activity</h2>
            <Link to="/executions" className="text-xs text-brand-600 hover:underline font-medium">
              View all →
            </Link>
          </div>
          {recentActivity.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">
              No recent node activity
            </div>
          ) : (
            <ul className="divide-y divide-gray-50">
              {recentActivity.map((node) => (
                <li key={node.id} className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50 transition-colors">
                  <div className="flex-1 min-w-0">
                    <Link to={`/nodes/${node.id}`} className="text-sm font-mono font-medium text-brand-600 hover:underline truncate block">
                      {node.hostname ?? node.minion_id}
                    </Link>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {node.status === 'online' ? (
                        <span className="text-emerald-600">online</span>
                      ) : (
                        <span className="text-red-500">{node.status}</span>
                      )}
                      {node.maintenance_mode && (
                        <span className="ml-2 text-amber-600">⚙ maintenance</span>
                      )}
                    </p>
                  </div>
                  {node.last_seen_at && (
                    <span className="text-xs text-gray-400 shrink-0">
                      {formatRelative(node.last_seen_at)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
