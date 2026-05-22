import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { fleetApi } from '../api/fleet'
import { useSaltKeysStore } from '../stores/saltKeysStore'
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

type CardVariant = 'green' | 'amber' | 'red' | 'blue' | 'neutral'

const CARD_STYLES: Record<CardVariant, {
  bar: string
  num: string
  bg: string
  border: string
  icon: string
}> = {
  green:   { bar: 'bg-gradient-to-r from-emerald-500 to-emerald-400', num: 'text-emerald-700', bg: 'bg-emerald-50/60',  border: 'border-emerald-100', icon: 'text-emerald-400' },
  amber:   { bar: 'bg-gradient-to-r from-amber-500 to-amber-400',    num: 'text-amber-700',   bg: 'bg-amber-50/60',    border: 'border-amber-100',   icon: 'text-amber-400'   },
  red:     { bar: 'bg-gradient-to-r from-red-500 to-red-400',        num: 'text-red-700',     bg: 'bg-red-50/60',      border: 'border-red-100',     icon: 'text-red-400'     },
  blue:    { bar: 'bg-gradient-to-r from-brand-500 to-brand-400',    num: 'text-brand-700',   bg: 'bg-brand-50/60',    border: 'border-brand-100',   icon: 'text-brand-400'   },
  neutral: { bar: 'bg-gradient-to-r from-gray-400 to-gray-300',      num: 'text-gray-900',    bg: 'bg-white',          border: 'border-gray-200',    icon: 'text-gray-300'    },
}

function StatCard({
  title,
  to,
  variant = 'neutral',
  value,
  icon,
  detail,
  sub,
}: {
  title: string
  to: string
  variant?: CardVariant
  value: React.ReactNode
  icon: string
  detail?: React.ReactNode
  sub?: React.ReactNode
}) {
  const s = CARD_STYLES[variant]
  return (
    <Link
      to={to}
      className={`block rounded-xl border ${s.border} ${s.bg} shadow-sm hover:shadow-md transition-all overflow-hidden`}
    >
      {/* Coloured top bar */}
      <div className={`h-1 w-full ${s.bar}`} />
      <div className="p-5">
        <div className="flex items-start justify-between mb-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</p>
          <span className={`text-2xl leading-none ${s.icon}`}>{icon}</span>
        </div>
        <p className={`text-4xl font-black tabular-nums leading-none mb-2 ${s.num}`}>
          {value}
        </p>
        {detail && <div className="text-xs space-y-0.5">{detail}</div>}
        {sub && <div className="mt-2 pt-2 border-t border-black/5 text-xs">{sub}</div>}
      </div>
    </Link>
  )
}

// ── Fleet status bar ───────────────────────────────────────────────────────────

function FleetStatusBar({
  online,
  offline,
  maint,
  total,
}: {
  online: number
  offline: number
  maint: number
  total: number
}) {
  if (!total) return null
  const unknownCount = Math.max(0, total - online - offline - maint)
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1.5">
        <span className="font-medium text-gray-700">Fleet Status</span>
        <span>{total} nodes total</span>
      </div>
      <div className="h-2.5 rounded-full overflow-hidden flex gap-px bg-gray-100">
        {online > 0 && (
          <div
            className="bg-emerald-500 transition-all"
            style={{ width: `${(online / total) * 100}%` }}
            title={`${online} online`}
          />
        )}
        {offline > 0 && (
          <div
            className="bg-red-400 transition-all"
            style={{ width: `${(offline / total) * 100}%` }}
            title={`${offline} offline`}
          />
        )}
        {maint > 0 && (
          <div
            className="bg-amber-400 transition-all"
            style={{ width: `${(maint / total) * 100}%` }}
            title={`${maint} maintenance`}
          />
        )}
        {unknownCount > 0 && (
          <div
            className="bg-gray-300 flex-1"
            title={`${unknownCount} unknown`}
          />
        )}
      </div>
      <div className="flex flex-wrap gap-4 mt-1.5 text-xs text-gray-500">
        {online > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
            {online} online
          </span>
        )}
        {offline > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400 inline-block" />
            {offline} offline
          </span>
        )}
        {maint > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" />
            {maint} maintenance
          </span>
        )}
        {unknownCount > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-gray-300 inline-block" />
            {unknownCount} other
          </span>
        )}
      </div>
    </div>
  )
}

// ── Main dashboard ─────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { data: overview, isFetching: overviewFetching } = useQuery({
    queryKey: ['fleet-overview'],
    queryFn: fleetApi.overview,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  const { data: nodesData, isFetching: nodesFetching } = useQuery({
    queryKey: ['dashboard-nodes'],
    queryFn: () => fleetApi.nodes({ page: 1, per_page: 50, sort: 'drift_score:desc' }),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const { data: security, isFetching: secFetching } = useQuery({
    queryKey: ['security-dashboard'],
    queryFn: () => api.get<SecurityDashboard>('/api/v1/security/dashboard'),
    staleTime: 60_000,
    refetchInterval: 30_000,
  })

  // Read from the store — SaltKeyWatcher in App.tsx already polls this every 30s
  const pendingKeys = useSaltKeysStore((s) => s.pendingCount)

  const { data: driftData, isFetching: driftFetching } = useQuery({
    queryKey: ['dashboard-drift'],
    queryFn: () => api.get<Paginated<DriftSummaryItem>>('/api/v1/drift?sort=drift_score:desc&per_page=5'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  // Live clock for the header (updates every minute)
  const [clockTime, setClockTime] = useState(() =>
    new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  )
  useEffect(() => {
    const id = setInterval(() => {
      setClockTime(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  const isRefetching = overviewFetching || nodesFetching || secFetching || driftFetching

  // Compute node counts
  const nodes: Node[] = nodesData?.items ?? []
  const totalNodes = overview?.total_nodes ?? 0
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

  // Keys variant (value comes from SaltKeyWatcher store)
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

  // Activity icon by node status
  function activityIcon(node: Node): string {
    if (node.maintenance_mode) return '⚙️'
    if (node.status === 'online') return '🟢'
    if (node.status === 'offline') return '🔴'
    return '⚫'
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Fleet Overview</h1>
          <p className="text-sm text-gray-500 mt-0.5">{clockTime} · refreshes every 30 seconds</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          {isRefetching ? (
            <>
              <span className="w-2 h-2 rounded-full bg-brand-500 animate-pulse inline-block" />
              <span>Updating…</span>
            </>
          ) : (
            <>
              <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />
              <span>Live</span>
            </>
          )}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Nodes card */}
        <StatCard
          title="Nodes"
          to="/fleet"
          variant={nodesVariant}
          value={totalNodes || '—'}
          icon="🖥️"
          detail={
            <>
              <p className="text-emerald-600 font-medium">{onlineCount} online</p>
              {offlineCount > 0 && <p className="text-red-500">{offlineCount} offline/stale</p>}
              {maintCount > 0 && <p className="text-amber-600">{maintCount} in maintenance</p>}
            </>
          }
        />

        {/* Drift card */}
        <StatCard
          title="Drift"
          to="/drift"
          variant={driftVariant}
          value={driftedCount}
          icon="📊"
          detail={
            <>
              <p className="text-gray-600">drifted nodes</p>
              <p className="text-gray-500">avg score {avgDrift}</p>
            </>
          }
        />

        {/* Security card */}
        <StatCard
          title="Security"
          to="/security"
          variant={secVariant}
          value={criticalCount}
          icon="🛡️"
          detail={
            <>
              <div className="flex gap-3 mt-0.5">
                {criticalCount > 0 && <span className="text-red-600 font-semibold">{criticalCount} critical</span>}
                {highCount > 0 && <span className="text-orange-600">{highCount} high</span>}
                {criticalCount === 0 && highCount === 0 && (
                  <span className="text-emerald-600">No critical/high</span>
                )}
              </div>
            </>
          }
        />

        {/* Salt Keys card */}
        <StatCard
          title="Minion Keys"
          to="/salt-keys"
          variant={keysVariant}
          value={pendingKeys}
          icon="🔑"
          detail={
            <p className={pendingKeys > 0 ? 'text-amber-600 font-medium' : 'text-gray-500'}>
              {pendingKeys > 0 ? `${pendingKeys} pending approval` : 'no pending keys'}
            </p>
          }
        />
      </div>

      {/* Fleet status stacked bar */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4">
        <FleetStatusBar
          online={onlineCount}
          offline={offlineCount}
          maint={maintCount}
          total={totalNodes}
        />
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
              {driftData ? 'All nodes in compliance ✓' : 'Loading…'}
            </div>
          ) : (
            <ul className="divide-y divide-gray-50">
              {topDrifted.map((d) => {
                const node = nodes.find((n) => n.id === d.node_id)
                const displayName = d.hostname ?? d.node_id.slice(0, 8)

                return (
                  <li key={d.node_id} className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50 transition-colors">
                    {node ? (
                      <Link to={`/nodes/${d.node_id}`} className="flex-1 text-sm font-mono font-medium text-brand-600 hover:underline truncate">
                        {displayName}
                      </Link>
                    ) : (
                      <span className="flex-1 text-sm font-mono font-medium text-gray-700 truncate">{displayName}</span>
                    )}
                    {/* Drift bar + score */}
                    <div className="flex items-center gap-2 shrink-0 w-32">
                      <span className={`font-bold text-sm w-8 text-right tabular-nums ${
                        d.drift_score > 50 ? 'text-red-600' :
                        d.drift_score > 20 ? 'text-amber-600' :
                        'text-emerald-600'
                      }`}>
                        {d.drift_score}
                      </span>
                      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            d.drift_score > 50 ? 'bg-red-500' :
                            d.drift_score > 20 ? 'bg-amber-400' :
                            'bg-emerald-400'
                          }`}
                          style={{ width: `${Math.min(100, d.drift_score)}%` }}
                        />
                      </div>
                    </div>
                    {d.computed_at && (
                      <span className="text-xs text-gray-400 shrink-0 w-12 text-right">
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
                  <span className="text-base leading-none shrink-0" title={node.status}>
                    {activityIcon(node)}
                  </span>
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
                        <span className="ml-2 text-amber-600">maintenance</span>
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
