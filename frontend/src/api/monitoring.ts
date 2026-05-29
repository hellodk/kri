import { api } from './client'

export interface NodeCounts {
  online: number
  stale: number
  offline: number
  unknown: number
  total: number
}

export interface AlertEvent {
  id: string
  message: string
  fired_at: string | null
}

export interface CeleryQueues {
  default: number
  maintenance: number
  drift: number
  sbom: number
  active: number
}

export interface HttpRequest {
  handler: string
  method: string
  status_code: string
  count: number
}

export interface FleetHealth {
  node_count: number
  avg_cpu_load_1m: number | null
  avg_mem_used_pct: number | null
  avg_disk_pct: number | null
  thermal_ok: number | null
  nodes_with_gpu: number
  total_gpu_vram_mb: number
}

export interface MonitoringSummary {
  node_counts: NodeCounts
  alert_events_24h: AlertEvent[]
  alert_count_24h: number
  celery_queues: CeleryQueues
  http_requests: HttpRequest[]
  fleet_health: FleetHealth
  generated_at: string
}

export const monitoringApi = {
  getSummary: () => api.get<MonitoringSummary>('/api/v1/monitoring/summary'),
}
