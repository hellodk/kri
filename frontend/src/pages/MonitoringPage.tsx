import { useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { monitoringApi, type MonitoringSummary, type FleetHealth } from '../api/monitoring'

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

// ── Fleet Health metric row ────────────────────────────────────────────────────

function cpuColor(val: number | null): string {
  if (val == null) return 'text-gray-400'
  if (val < 70) return 'text-emerald-600'
  if (val <= 90) return 'text-amber-600'
  return 'text-red-600'
}

function memColor(val: number | null): string {
  if (val == null) return 'text-gray-400'
  if (val < 75) return 'text-emerald-600'
  if (val <= 90) return 'text-amber-600'
  return 'text-red-600'
}

function diskColor(val: number | null): string {
  if (val == null) return 'text-gray-400'
  if (val < 80) return 'text-emerald-600'
  if (val <= 90) return 'text-amber-600'
  return 'text-red-600'
}

function MetricCard({
  label,
  badge,
  value,
  colorClass,
  sub,
}: {
  label: string
  badge?: string
  value: string
  colorClass: string
  sub: string
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</span>
        {badge && <span className="text-xs text-gray-300">{badge}</span>}
      </div>
      <div className={`text-3xl font-black tabular-nums ${colorClass}`}>{value}</div>
      <div className="text-xs text-gray-400 mt-1">{sub}</div>
    </div>
  )
}

function FleetHealthRow({ fh }: { fh: FleetHealth }) {
  if (fh.node_count === 0) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-sm text-gray-500 mb-6">
        No fleet health data available. Go to <strong>Fleet Health</strong> tab and click{' '}
        <strong>Collect Now</strong>.
      </div>
    )
  }

  const cpuVal = fh.avg_cpu_load_1m != null ? Math.round(fh.avg_cpu_load_1m) : null
  const memVal = fh.avg_mem_used_pct != null ? Math.round(fh.avg_mem_used_pct) : null
  const diskVal = fh.avg_disk_pct != null ? Math.round(fh.avg_disk_pct) : null

  const gpuLabel =
    fh.nodes_with_gpu === 0
      ? '—'
      : `${fh.nodes_with_gpu} node${fh.nodes_with_gpu !== 1 ? 's' : ''} · ${(fh.total_gpu_vram_mb / 1024).toFixed(0)} GB`

  const thermalOk = fh.thermal_ok !== null && fh.thermal_ok === fh.node_count
  const thermalVal =
    fh.thermal_ok == null ? '—' : `${fh.thermal_ok}/${fh.node_count}`
  const thermalColor = fh.thermal_ok == null ? 'text-gray-400' : thermalOk ? 'text-emerald-600' : 'text-amber-600'

  return (
    <div className="grid grid-cols-5 gap-4 mb-6">
      <MetricCard
        label="CPU Load Avg"
        badge="1m"
        value={cpuVal != null ? `${cpuVal}%` : '—'}
        colorClass={cpuColor(cpuVal)}
        sub={`${fh.node_count} node${fh.node_count !== 1 ? 's' : ''} reporting`}
      />
      <MetricCard
        label="Memory Avg"
        value={memVal != null ? `${memVal}%` : '—'}
        colorClass={memColor(memVal)}
        sub={`${fh.node_count} node${fh.node_count !== 1 ? 's' : ''} reporting`}
      />
      <MetricCard
        label="Disk Avg"
        value={diskVal != null ? `${diskVal}%` : '—'}
        colorClass={diskColor(diskVal)}
        sub={`${fh.node_count} node${fh.node_count !== 1 ? 's' : ''} reporting`}
      />
      <MetricCard
        label="GPU Nodes"
        value={gpuLabel}
        colorClass="text-[#444ce7]"
        sub={fh.nodes_with_gpu === 0 ? 'No GPU nodes' : `${fh.total_gpu_vram_mb.toLocaleString()} MB total VRAM`}
      />
      <MetricCard
        label="Thermal"
        value={thermalVal}
        colorClass={thermalColor}
        sub={thermalOk ? 'All nodes OK' : 'Some nodes hot'}
      />
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
                <th className="text-left py-1.5 px-1 font-semibold text-gray-500 uppercase tracking-wide">Endpoint</th>
                <th className="text-right py-1.5 px-1 font-semibold text-gray-500 uppercase tracking-wide">Count</th>
              </tr>
            </thead>
            <tbody>
              {http_requests.map((r, i) => {
                const pct = (r.count / maxCount) * 100
                const isError = r.status_code.startsWith('4') || r.status_code.startsWith('5')
                const endpointLabel = `${r.method} ${r.status_code}`
                return (
                  <tr
                    key={i}
                    className="border-b border-gray-50 hover:bg-gray-50 transition-colors"
                  >
                    <td className="py-1.5 px-1">
                      <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded font-medium font-mono ${isError ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                        {endpointLabel}
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
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) + ' IST'
    : null

  return (
    <div className="max-w-screen-xl mx-auto">
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

      {/* Beat dead-man's-switch warning */}
      {data && data.maintenance_heartbeat.beat_ok === false && (
        <div className="mb-4 flex items-start gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-800">
          <span className="text-lg leading-none flex-shrink-0">⚠</span>
          <div>
            <p className="font-semibold">Celery Beat worker appears stuck or down</p>
            <p className="text-red-700 mt-0.5">
              <code className="font-mono">mark_stale_nodes</code> has not run in the last 10 minutes.
              Node status transitions (online → stale → offline) are frozen.
              {data.maintenance_heartbeat.last_run_at
                ? ` Last run: ${format(parseISO(data.maintenance_heartbeat.last_run_at), 'HH:mm:ss')}.`
                : ' No run recorded since kri started.'}
            </p>
            <p className="text-red-600 mt-1 text-xs">Check: <code className="font-mono">kri logs beat</code></p>
          </div>
        </div>
      )}

      {/* Content */}
      {data && (
        <>
          {/* Fleet health metric row */}
          <FleetHealthRow fh={data.fleet_health} />

          {/* Main 2-col grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <NodeStatusCard data={data} />
            <CeleryQueuesCard data={data} />
            <AlertEventsCard data={data} />
            <HttpRequestsCard data={data} />
          </div>
        </>
      )}
    </div>
  )
}
