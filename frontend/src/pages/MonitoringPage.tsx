import { useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { monitoringApi, type MonitoringSummary } from '../api/monitoring'

// ── Shared card wrapper ────────────────────────────────────────────────────────

function SectionCard({
  title,
  icon,
  barColor,
  children,
}: {
  title: string
  icon: string
  barColor: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className={`h-1 w-full ${barColor}`} />
      <div className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-lg leading-none">{icon}</span>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{title}</h2>
        </div>
        {children}
      </div>
    </div>
  )
}

// ── Node Status card ───────────────────────────────────────────────────────────

function NodeStatusCard({ data }: { data: MonitoringSummary }) {
  const { node_counts: nc } = data
  const total = nc.total || 1 // avoid div/0

  const segments = [
    { label: 'Online', count: nc.online, color: 'bg-emerald-500', dot: 'bg-emerald-500', text: 'text-emerald-700' },
    { label: 'Stale', count: nc.stale, color: 'bg-amber-400', dot: 'bg-amber-400', text: 'text-amber-700' },
    { label: 'Offline', count: nc.offline, color: 'bg-red-400', dot: 'bg-red-400', text: 'text-red-700' },
    { label: 'Unknown', count: nc.unknown, color: 'bg-gray-300', dot: 'bg-gray-400', text: 'text-gray-600' },
  ]

  return (
    <SectionCard
      title="Node Status"
      icon="⬡"
      barColor="bg-gradient-to-r from-emerald-500 to-emerald-400"
    >
      {/* Big total */}
      <p className="text-5xl font-black tabular-nums text-gray-900 leading-none mb-4">
        {nc.total}
        <span className="text-lg font-normal text-gray-400 ml-2">nodes</span>
      </p>

      {/* Stacked bar */}
      <div className="h-3 rounded-full overflow-hidden flex gap-px bg-gray-100 mb-3">
        {segments.map(({ count, color }) =>
          count > 0 ? (
            <div
              key={color}
              className={`${color} transition-all`}
              style={{ width: `${(count / total) * 100}%` }}
            />
          ) : null
        )}
      </div>

      {/* Legend */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
        {segments.map(({ label, count, dot, text }) => (
          <div key={label} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-1.5 text-gray-600">
              <span className={`w-2 h-2 rounded-full ${dot} flex-shrink-0`} />
              {label}
            </span>
            <span className={`font-semibold tabular-nums ${text}`}>{count}</span>
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

// ── Celery Queues card ─────────────────────────────────────────────────────────

function CeleryQueuesCard({ data }: { data: MonitoringSummary }) {
  const { celery_queues: q } = data
  const queues = [
    { name: 'default', label: 'Default', count: q.default },
    { name: 'maintenance', label: 'Maintenance', count: q.maintenance },
    { name: 'drift', label: 'Drift', count: q.drift },
    { name: 'sbom', label: 'SBOM', count: q.sbom },
  ]
  const total = queues.reduce((s, x) => s + x.count, 0)

  return (
    <SectionCard
      title="Celery Queue Depth"
      icon="▷"
      barColor="bg-gradient-to-r from-brand-500 to-brand-400"
    >
      <div className="flex items-end gap-4 mb-4">
        <p className="text-5xl font-black tabular-nums text-gray-900 leading-none">
          {total}
          <span className="text-lg font-normal text-gray-400 ml-2">pending</span>
        </p>
        <p className="text-sm text-gray-500 mb-1">
          <span className="font-semibold tabular-nums text-gray-700">{q.active}</span>
          <span className="ml-1">active</span>
        </p>
      </div>

      <div className="space-y-2">
        {queues.map(({ label, count }) => {
          const pct = total > 0 ? (count / total) * 100 : 0
          const isHigh = count > 10
          return (
            <div key={label}>
              <div className="flex items-center justify-between text-sm mb-0.5">
                <span className="text-gray-600">{label}</span>
                <span className={`font-semibold tabular-nums ${isHigh ? 'text-amber-700' : 'text-gray-900'}`}>
                  {count}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${isHigh ? 'bg-amber-400' : 'bg-brand-400'}`}
                  style={{ width: `${Math.max(pct, count > 0 ? 2 : 0)}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

// ── Alert Events card ──────────────────────────────────────────────────────────

function AlertEventsCard({ data }: { data: MonitoringSummary }) {
  const { alert_events_24h, alert_count_24h } = data

  return (
    <SectionCard
      title="Alert Events (24h)"
      icon="◭"
      barColor={alert_count_24h > 0
        ? 'bg-gradient-to-r from-red-500 to-red-400'
        : 'bg-gradient-to-r from-gray-300 to-gray-200'}
    >
      <p className="text-5xl font-black tabular-nums leading-none mb-4">
        <span className={alert_count_24h > 0 ? 'text-red-700' : 'text-gray-900'}>
          {alert_count_24h}
        </span>
        <span className="text-lg font-normal text-gray-400 ml-2">alerts</span>
      </p>

      {alert_events_24h.length === 0 ? (
        <p className="text-sm text-gray-400">No alerts in the last 24 hours.</p>
      ) : (
        <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
          {alert_events_24h.map((ev) => (
            <div
              key={ev.id}
              className="flex items-start gap-2 text-xs py-1.5 border-b border-gray-100 last:border-0"
            >
              <span className="flex-shrink-0 text-red-500 mt-0.5">◭</span>
              <div className="min-w-0 flex-1">
                <p className="text-gray-800 leading-snug">{ev.message}</p>
                {ev.fired_at && (
                  <p className="text-gray-400 mt-0.5">
                    {format(parseISO(ev.fired_at), 'MMM d, HH:mm')}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  )
}

// ── HTTP Requests card ─────────────────────────────────────────────────────────

function HttpRequestsCard({ data }: { data: MonitoringSummary }) {
  const { http_requests } = data
  const maxCount = http_requests.reduce((m, r) => Math.max(m, r.count), 1)

  return (
    <SectionCard
      title="HTTP Requests (since startup)"
      icon="◈"
      barColor="bg-gradient-to-r from-gray-400 to-gray-300"
    >
      {http_requests.length === 0 ? (
        <p className="text-sm text-gray-400">No HTTP metrics available yet.</p>
      ) : (
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-1.5 px-1 font-semibold text-gray-500 uppercase tracking-wide">Handler</th>
                <th className="text-left py-1.5 px-1 font-semibold text-gray-500 uppercase tracking-wide">Method</th>
                <th className="text-left py-1.5 px-1 font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                <th className="text-right py-1.5 px-1 font-semibold text-gray-500 uppercase tracking-wide">Count</th>
              </tr>
            </thead>
            <tbody>
              {http_requests.map((r, i) => {
                const pct = (r.count / maxCount) * 100
                const isError = r.status_code.startsWith('4') || r.status_code.startsWith('5')
                return (
                  <tr
                    key={i}
                    className="border-b border-gray-50 hover:bg-gray-50 transition-colors"
                  >
                    <td className="py-1.5 px-1 text-gray-700 font-mono max-w-[200px] truncate" title={r.handler}>
                      {r.handler}
                    </td>
                    <td className="py-1.5 px-1 text-gray-600">{r.method}</td>
                    <td className="py-1.5 px-1">
                      <span className={`px-1.5 py-0.5 rounded font-medium ${isError ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                        {r.status_code}
                      </span>
                    </td>
                    <td className="py-1.5 px-1 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 rounded-full bg-gray-100 overflow-hidden hidden sm:block">
                          <div
                            className="h-full rounded-full bg-brand-400"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="font-semibold tabular-nums text-gray-900">{r.count.toLocaleString()}</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  )
}

// ── Loading skeleton ───────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden animate-pulse">
      <div className="h-1 w-full bg-gray-200" />
      <div className="p-5 space-y-3">
        <div className="h-3 bg-gray-100 rounded w-1/3" />
        <div className="h-10 bg-gray-100 rounded w-1/2" />
        <div className="h-2 bg-gray-100 rounded w-full" />
        <div className="h-2 bg-gray-100 rounded w-5/6" />
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function MonitoringPage() {
  const qc = useQueryClient()

  const { data, isLoading, error, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ['monitoring-summary'],
    queryFn: monitoringApi.getSummary,
    refetchInterval: 60_000,
  })

  function handleRefresh() {
    qc.invalidateQueries({ queryKey: ['monitoring-summary'] })
  }

  const lastUpdated = dataUpdatedAt
    ? format(new Date(dataUpdatedAt), 'HH:mm:ss')
    : null

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Monitoring</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Platform stats — node status, queue depth, alert events, API throughput
            {lastUpdated && (
              <span className="ml-2 text-gray-400">
                · Updated {lastUpdated}
                {isFetching && <span className="ml-1 text-brand-500">·  refreshing…</span>}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isFetching}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          Failed to load monitoring data. Check that you have operator or admin access.
        </div>
      )}

      {/* Loading skeleton */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* Content grid */}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <NodeStatusCard data={data} />
          <CeleryQueuesCard data={data} />
          <AlertEventsCard data={data} />
          <HttpRequestsCard data={data} />
        </div>
      )}
    </div>
  )
}
