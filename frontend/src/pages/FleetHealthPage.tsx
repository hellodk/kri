// frontend/src/pages/FleetHealthPage.tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import {
  fleetHealthApi, type NodeHealthSnapshot, formatUptime, formatPower, thermalColor,
} from '../api/fleetHealth'
import { useToastStore } from '../stores/toastStore'

function MetricBar({ value, alert }: { value: number | null; alert: boolean }) {
  const pct = value ?? 0
  return (
    <div className="w-full bg-gray-200 rounded-full h-2 mt-1">
      <div
        className={`h-2 rounded-full transition-all ${alert ? 'bg-red-500' : pct > 70 ? 'bg-yellow-400' : 'bg-green-500'}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

function NodeCard({
  snap,
  onSelect,
  selected,
}: {
  snap: NodeHealthSnapshot
  onSelect: (id: string) => void
  selected: boolean
}) {
  const hasAlert = snap.disk_alert || snap.mem_alert || snap.thermal_alert
  const borderColor = hasAlert ? 'border-red-400 bg-red-50' : 'border-gray-200 bg-white'

  return (
    <div
      className={`border rounded-lg p-4 cursor-pointer transition-shadow hover:shadow-md ${borderColor} ${selected ? 'ring-2 ring-blue-500' : ''}`}
      onClick={() => onSelect(snap.node_id)}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="font-semibold text-gray-900 text-sm truncate">
          {snap.hostname ?? snap.minion_id}
        </span>
        {hasAlert && (
          <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">Alert</span>
        )}
      </div>

      <div className="space-y-2 text-xs text-gray-700">
        <div>
          <div className="flex justify-between">
            <span>Disk</span>
            <span className={snap.disk_alert ? 'text-red-600 font-semibold' : ''}>
              {snap.disk_root_pct != null ? `${snap.disk_root_pct}%` : '—'}
              {snap.disk_root_used_gb != null && snap.disk_root_total_gb != null
                ? ` (${Number(snap.disk_root_used_gb).toFixed(0)} / ${Number(snap.disk_root_total_gb).toFixed(0)} GB)`
                : ''}
            </span>
          </div>
          <MetricBar value={snap.disk_root_pct} alert={snap.disk_alert} />
        </div>

        <div>
          <div className="flex justify-between">
            <span>Memory</span>
            <span className={snap.mem_alert ? 'text-red-600 font-semibold' : ''}>
              {snap.mem_used_pct != null ? `${snap.mem_used_pct}%` : '—'}
              {snap.mem_total_gb != null ? ` (${Number(snap.mem_total_gb).toFixed(0)} GB)` : ''}
            </span>
          </div>
          <MetricBar value={snap.mem_used_pct} alert={snap.mem_alert} />
        </div>

        <div className="flex justify-between">
          <span>CPU Load</span>
          <span>
            {snap.cpu_load_1m != null
              ? `${Number(snap.cpu_load_1m).toFixed(2)} / ${snap.cpu_load_5m != null ? Number(snap.cpu_load_5m).toFixed(2) : '—'} / ${snap.cpu_load_15m != null ? Number(snap.cpu_load_15m).toFixed(2) : '—'}`
              : '—'}
          </span>
        </div>

        {snap.gpu_name && (
          <div className="flex justify-between">
            <span>GPU</span>
            <span className="truncate max-w-[160px]" title={snap.gpu_name}>
              {snap.gpu_name}
              {snap.gpu_vram_mb ? ` (${snap.gpu_vram_mb >= 1024 ? `${Math.floor(snap.gpu_vram_mb / 1024)} GB` : `${snap.gpu_vram_mb} MB`})` : ''}
            </span>
          </div>
        )}

        {(snap.cpu_power_mw != null || snap.gpu_power_mw != null) && (
          <div className="flex justify-between">
            <span>Power</span>
            <span>CPU {formatPower(snap.cpu_power_mw)} · GPU {formatPower(snap.gpu_power_mw)}</span>
          </div>
        )}

        <div className="flex justify-between">
          <span>Thermal</span>
          <span className={thermalColor(snap.thermal_pressure)}>
            {snap.thermal_pressure ?? '—'}
          </span>
        </div>

        <div className="flex justify-between">
          <span>Uptime</span>
          <span>{formatUptime(snap.uptime_seconds)}</span>
        </div>

        <div className="text-gray-400 text-right">
          {format(parseISO(snap.collected_at), 'MMM d, HH:mm')}
        </div>

        {snap.error && (
          <div className="text-red-500 text-xs truncate" title={snap.error}>
            ⚠ {snap.error}
          </div>
        )}
      </div>
    </div>
  )
}

function HistoryPanel({ nodeId, hostname }: { nodeId: string; hostname: string | null }) {
  const { data: history = [], isLoading } = useQuery({
    queryKey: ['fleet-health-history', nodeId],
    queryFn: () => fleetHealthApi.getNodeHistory(nodeId, 24),
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-gray-500">Loading history…</div>
  if (history.length === 0) return <div className="p-6 text-sm text-gray-500">No history in the last 24h.</div>

  const chartData = history.map(s => ({
    time: format(parseISO(s.collected_at), 'HH:mm'),
    disk: s.disk_root_pct,
    mem: s.mem_used_pct,
    cpu1: s.cpu_load_1m != null ? Number(Number(s.cpu_load_1m).toFixed(2)) : null,
    cpuPowerW: s.cpu_power_mw != null ? Number((s.cpu_power_mw / 1000).toFixed(2)) : null,
  }))

  return (
    <div className="border-t border-gray-200 bg-white p-6">
      <h3 className="font-semibold text-gray-900 mb-4">
        {hostname ?? nodeId} — Last 24h
      </h3>
      <div className="space-y-6">
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">Disk &amp; Memory %</p>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
              <Tooltip />
              <Line type="monotone" dataKey="disk" stroke="#3b82f6" dot={false} name="Disk %" />
              <Line type="monotone" dataKey="mem" stroke="#f59e0b" dot={false} name="Mem %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">CPU Load (1m avg)</p>
          <ResponsiveContainer width="100%" height={100}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="cpu1" stroke="#10b981" dot={false} name="Load 1m" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        {chartData.some(d => d.cpuPowerW != null) && (
          <div>
            <p className="text-xs font-medium text-gray-600 mb-1">CPU Power (W)</p>
            <ResponsiveContainer width="100%" height={100}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="time" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="W" />
                <Tooltip />
                <Line type="monotone" dataKey="cpuPowerW" stroke="#8b5cf6" dot={false} name="CPU Power" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}

export default function FleetHealthPage() {
  const qc = useQueryClient()
  const toast = useToastStore(s => s.add)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const { data: snapshots = [], isLoading, error } = useQuery({
    queryKey: ['fleet-health'],
    queryFn: () => fleetHealthApi.getFleetHealth(),
    refetchInterval: 60_000,
  })

  const collectMut = useMutation({
    mutationFn: () => fleetHealthApi.triggerCollect(),
    onSuccess: () => {
      toast('Health collection queued. Data refreshes in ~60s.', 'success')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['fleet-health'] }), 5000)
    },
    onError: () => toast('Failed to trigger collection.', 'error'),
  })

  const alertCount = snapshots.filter(s => s.disk_alert || s.mem_alert || s.thermal_alert).length
  const selected = snapshots.find(s => s.node_id === selectedNodeId) ?? null

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Fleet Health</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {snapshots.length} node{snapshots.length !== 1 ? 's' : ''}
            {alertCount > 0 && (
              <span className="ml-2 text-red-600 font-medium">· {alertCount} alert{alertCount !== 1 ? 's' : ''}</span>
            )}
          </p>
        </div>
        <button
          onClick={() => collectMut.mutate()}
          disabled={collectMut.isPending}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-colors"
        >
          {collectMut.isPending ? 'Queuing…' : 'Collect Now'}
        </button>
      </div>

      {alertCount > 0 && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          ⚠ {alertCount} node{alertCount !== 1 ? 's are' : ' is'} above threshold — disk ≥ 85% or memory ≥ 90% or thermal pressure detected.
        </div>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="border border-gray-200 rounded-lg p-4 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
              <div className="space-y-2">
                {[...Array(5)].map((_, j) => <div key={j} className="h-3 bg-gray-100 rounded" />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="text-red-600 text-sm">Failed to load fleet health data.</div>
      )}

      {!isLoading && !error && snapshots.length === 0 && (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg font-medium">No health data yet.</p>
          <p className="text-sm mt-1">Click <strong>Collect Now</strong> to gather metrics from online nodes.</p>
        </div>
      )}

      {snapshots.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {snapshots.map(snap => (
            <NodeCard
              key={snap.node_id}
              snap={snap}
              selected={selectedNodeId === snap.node_id}
              onSelect={id => setSelectedNodeId(prev => prev === id ? null : id)}
            />
          ))}
        </div>
      )}

      {selected && (
        <div className="mt-6 rounded-lg border border-gray-200 overflow-hidden">
          <HistoryPanel nodeId={selected.node_id} hostname={selected.hostname} />
        </div>
      )}
    </div>
  )
}
