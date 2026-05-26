// frontend/src/api/fleetHealth.ts
import { api } from './client'

export interface NodeHealthSnapshot {
  id: string
  node_id: string
  minion_id: string
  hostname: string | null
  collected_at: string
  disk_root_used_gb: number | null
  disk_root_total_gb: number | null
  disk_root_pct: number | null
  disk_root_inodes_pct: number | null
  mem_total_gb: number | null
  mem_available_gb: number | null
  mem_used_pct: number | null
  cpu_load_1m: number | null
  cpu_load_5m: number | null
  cpu_load_15m: number | null
  uptime_seconds: number | null
  gpu_name: string | null
  gpu_vram_mb: number | null
  cpu_power_mw: number | null
  gpu_power_mw: number | null
  thermal_pressure: string | null
  error: string | null
  // computed by API
  disk_alert: boolean
  mem_alert: boolean
  thermal_alert: boolean
}

export const fleetHealthApi = {
  getFleetHealth: () => api.get<NodeHealthSnapshot[]>('/api/v1/fleet-health'),
  triggerCollect: () => api.post<{ status: string; message: string }>('/api/v1/fleet-health/collect', {}),
  getNodeHistory: (nodeId: string, hours = 24) =>
    api.get<NodeHealthSnapshot[]>(`/api/v1/fleet-health/${nodeId}/history?hours=${hours}`),
}

export function formatUptime(seconds: number | null): string {
  if (seconds === null) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function formatPower(mw: number | null): string {
  if (mw === null) return '—'
  return mw >= 1000 ? `${(mw / 1000).toFixed(1)} W` : `${mw} mW`
}

export function thermalColor(pressure: string | null): string {
  switch (pressure) {
    case 'Nominal': return 'text-green-600'
    case 'Light': return 'text-yellow-500'
    case 'Moderate': return 'text-orange-500'
    case 'Heavy': return 'text-red-600'
    case 'Critical': return 'text-red-800 font-bold'
    default: return 'text-gray-400'
  }
}
