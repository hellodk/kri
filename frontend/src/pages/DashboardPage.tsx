import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { fleetApi } from '../api/fleet'
import { saltMastersApi } from '../api/saltMasters'
import { masterHealthSummary } from '../lib/masterNodes'
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

function StatCard({
  title,
  to,
  accent,
  numColor,
  value,
  detail,
}: {
  title: string
  to: string
  accent: string
  numColor: string
  value: React.ReactNode
  detail?: React.ReactNode
}) {
  return (
    <Link
      to={to}
      className={`block bg-white rounded-xl border border-gray-200 border-l-4 ${accent} p-5 shadow-sm hover:shadow-md transition-shadow`}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">{title}</p>
      <p className={`text-4xl font-black tabular-nums leading-none mb-2 ${numColor}`}>{value}</p>
      {detail && <div className="text-xs space-y-0.5 text-gray-500">{detail}</div>}
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

  const { data: saltMasters } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
  const mastersHealth = masterHealthSummary(saltMasters ?? [])

  const { data: driftData, isFetching: driftFetching } = useQuery({
    queryKey: ['dashboard-drift'],
    queryFn: () => api.get<Paginated<DriftSummaryItem>>('/api/v1/drift?sort=drift_score:desc&per_page=5'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  // Live clock for the header (updates every minute)
  const [clockTime, setClockTime] = useState(() =>
    new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })
  )
  useEffect(() => {
    const id = setInterval(() => {
      setClockTime(new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }))
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

  // Drift variant
  const avgDrift = overview?.avg_drift_score ?? 0
  const driftedCount = (overview?.nodes_medium ?? 0) + (overview?.nodes_high ?? 0) + (overview?.nodes_critical ?? 0)

  // Keys variant (value comes from SaltKeyWatcher store)

  // Nodes variant

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
          title="Total Nodes"
          to="/fleet"
          accent="border-l-brand-600"
          numColor="text-gray-900"
          value={totalNodes || '—'}
          detail={
            <>
              <span className="text-emerald-600 font-medium">{onlineCount} online</span>
              {offlineCount > 0 && <span className="ml-2 text-red-500">{offlineCount} offline/stale</span>}
              {maintCount > 0 && <span className="ml-2 text-amber-600">{maintCount} maintenance</span>}
            </>
          }
        />

        {/* Drift card */}
        <StatCard
          title="Drift"
          to="/compliance?tab=drift"
          accent={driftedCount === 0 ? 'border-l-emerald-500' : avgDrift > 50 ? 'border-l-red-500' : 'border-l-amber-500'}
          numColor={driftedCount === 0 ? 'text-emerald-700' : avgDrift > 50 ? 'text-red-700' : 'text-amber-700'}
          value={driftedCount}
          detail={<>drifted nodes · avg score {avgDrift}</>}
        />

        {/* Security card */}
        <StatCard
          title="Security"
          to="/compliance?tab=security"
          accent={criticalCount > 0 ? 'border-l-red-500' : highCount > 0 ? 'border-l-amber-500' : 'border-l-emerald-500'}
          numColor={criticalCount > 0 ? 'text-red-700' : highCount > 0 ? 'text-amber-700' : 'text-emerald-700'}
          value={criticalCount + highCount}
          detail={
            criticalCount === 0 && highCount === 0
              ? 'No critical/high findings'
              : `${criticalCount} critical · ${highCount} high`
          }
        />

        {/* Salt Keys card */}
        <StatCard
          title="Minion Keys"
          to="/automation?tab=salt-keys"
          accent={pendingKeys > 0 ? 'border-l-amber-500' : 'border-l-gray-300'}
          numColor={pendingKeys > 0 ? 'text-amber-700' : 'text-gray-900'}
          value={pendingKeys}
          detail={pendingKeys > 0 ? `${pendingKeys} pending approval` : 'no pending keys'}
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

      {/* Salt Masters health widget — only rendered when at least one master exists */}
      {mastersHealth.total > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              {/* Server icon */}
              <svg className="w-4 h-4 text-indigo-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
              </svg>
              <h2 className="text-sm font-semibold text-gray-800">
                Salt Masters
                <span className="ml-2 text-xs font-normal text-gray-500">
                  {mastersHealth.total} registered
                </span>
              </h2>
            </div>
            <Link
              to="/settings?tab=Salt Masters"
              className="text-xs text-brand-600 hover:underline font-medium"
            >
              Manage →
            </Link>
          </div>
          {/* Counts row — label + count, not color-only */}
          <div className="flex flex-wrap gap-4">
            {mastersHealth.healthy > 0 && (
              <span className="flex items-center gap-1.5 text-sm">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 flex-shrink-0" aria-hidden="true" />
                <span className="font-semibold text-emerald-700 tabular-nums">{mastersHealth.healthy}</span>
                <span className="text-gray-500">Healthy</span>
              </span>
            )}
            {mastersHealth.degraded > 0 && (
              <span className="flex items-center gap-1.5 text-sm">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500 flex-shrink-0" aria-hidden="true" />
                <span className="font-semibold text-amber-700 tabular-nums">{mastersHealth.degraded}</span>
                <span className="text-gray-500">Degraded</span>
              </span>
            )}
            {mastersHealth.unreachable > 0 && (
              <span className="flex items-center gap-1.5 text-sm">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500 flex-shrink-0" aria-hidden="true" />
                <span className="font-semibold text-red-700 tabular-nums">{mastersHealth.unreachable}</span>
                <span className="text-gray-500">Unreachable</span>
              </span>
            )}
            {mastersHealth.unknown > 0 && (
              <span className="flex items-center gap-1.5 text-sm">
                <span className="w-2.5 h-2.5 rounded-full bg-gray-400 flex-shrink-0" aria-hidden="true" />
                <span className="font-semibold text-gray-700 tabular-nums">{mastersHealth.unknown}</span>
                <span className="text-gray-500">Unknown</span>
              </span>
            )}
            {/* All healthy summary */}
            {mastersHealth.healthy === mastersHealth.total && (
              <span className="ml-auto text-xs text-emerald-600 font-medium">All healthy ✓</span>
            )}
            {/* Alert label when any are unreachable */}
            {mastersHealth.unreachable > 0 && (
              <span className="ml-auto text-xs text-red-600 font-semibold">
                {mastersHealth.unreachable} unreachable — check Salt Masters
              </span>
            )}
          </div>
        </div>
      )}

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
                      <span className="text-xs text-gray-500 shrink-0 w-12 text-right">
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
            <div className="px-5 py-8 text-center text-sm text-gray-600">
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
                    <p className="text-xs text-gray-500 mt-0.5">
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
                    <span className="text-xs text-gray-500 shrink-0">
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
