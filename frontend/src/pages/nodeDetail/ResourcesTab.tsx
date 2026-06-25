import { memo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { Sparkline } from './Sparkline'
import { AiRecommendationPanel } from './AiRecommendationPanel'

export const ResourcesTab = memo(function ResourcesTab({
  nodeId,
  aiLoading,
  aiRecommendation,
  aiError,
  onAskAI,
}: {
  nodeId: string
  aiLoading: boolean
  aiRecommendation: string | null
  aiError: string | null
  onAskAI: () => void
}) {
  const [metricsRange, setMetricsRange] = useState<'15m' | '1h' | '6h' | '24h'>('1h')

  const { data: metricsData, isLoading: metricsLoading, refetch: refetchMetrics } = useQuery({
    queryKey: ['node-metrics', nodeId, metricsRange],
    queryFn: () => api.get<{
      available: boolean; reason?: string; instance?: string; range?: string;
      series?: Record<string, Array<{ t: number; v: number }>>
    }>(`/api/v1/nodes/${nodeId}/metrics?range=${metricsRange}`),
    enabled: !!nodeId,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  return (
    <div role="tabpanel" id="tabpanel-resources" aria-labelledby="tab-resources" className="space-y-4">
      {/* Header + range selector */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Resource Usage</h3>
        <div className="flex items-center gap-2">
          {(['15m', '1h', '6h', '24h'] as const).map(r => (
            <button key={r} onClick={() => setMetricsRange(r)}
              className={`px-2.5 py-1 text-xs rounded font-medium ${metricsRange === r ? 'bg-brand-600 text-white' : 'bg-white border border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
              {r}
            </button>
          ))}
          <button onClick={() => refetchMetrics()} disabled={metricsLoading}
            className="px-2.5 py-1 text-xs rounded bg-white border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            ↺
          </button>
        </div>
      </div>

      {metricsLoading ? (
        <div className="flex items-center justify-center py-16 text-sm text-gray-500" role="status" aria-live="polite">
          <div className="w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mr-2" />
          Querying Prometheus…
        </div>
      ) : !metricsData?.available ? (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center">
          <p className="text-sm font-medium text-amber-800">Metrics not available</p>
          <p className="text-xs text-amber-600 mt-1">{metricsData?.reason ?? 'Unknown reason'}</p>
          <p className="text-xs text-gray-500 mt-2">
            Deploy node_exporter via the Overview tab → Deploy Monitoring button.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            { key: 'cpu', label: 'CPU Usage', unit: '%', color: '#ef4444', warn: 80 },
            { key: 'mem_used_pct', label: 'Memory Usage', unit: '%', color: '#8b5cf6', warn: 85 },
            { key: 'disk_read_kbs', label: 'Disk Read', unit: 'KB/s', color: '#06b6d4', warn: null },
            { key: 'disk_write_kbs', label: 'Disk Write', unit: 'KB/s', color: '#f59e0b', warn: null },
            { key: 'net_rx_kbs', label: 'Network In', unit: 'KB/s', color: '#10b981', warn: null },
            { key: 'net_tx_kbs', label: 'Network Out', unit: 'KB/s', color: '#6366f1', warn: null },
          ].map(({ key, label, unit, color, warn }) => {
            const series = metricsData?.series?.[key] ?? []
            const last = series.length > 0 ? series[series.length - 1].v : null
            const isHigh = warn !== null && last !== null && last > warn
            return (
              <div key={key} className={`bg-white border rounded-xl p-4 ${isHigh ? 'border-red-300 bg-red-50' : 'border-gray-200'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">{label}</span>
                  {last !== null && (
                    <span className={`text-sm font-bold ${isHigh ? 'text-red-600' : 'text-gray-800'}`}>
                      {last.toFixed(1)} {unit}
                      {isHigh && <span className="ml-1 text-xs">⚠</span>}
                    </span>
                  )}
                </div>
                <Sparkline data={series} color={isHigh ? '#ef4444' : color} height={36} />
              </div>
            )
          })}
        </div>
      )}

      <p className="text-xs text-gray-500 text-center">
        Source: Prometheus ({metricsData?.instance}) · Refreshes every 30s
      </p>

      {/* AI Recommendations — Resources tab */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-base">🤖</span>
            <h3 className="text-sm font-semibold text-gray-900">AI Analysis</h3>
            <span className="text-xs text-gray-500">Resource usage, drift &amp; alerts</span>
          </div>
          <button
            onClick={onAskAI}
            disabled={aiLoading}
            className="px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {aiLoading ? (
              <><span className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin inline-block" />Analyzing…</>
            ) : (
              'Get AI Analysis'
            )}
          </button>
        </div>

        {aiRecommendation ? (
          <AiRecommendationPanel text={aiRecommendation} />
        ) : aiError ? (
          <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
            <span className="text-red-500 mt-0.5">⚠</span>
            <p className="text-sm text-red-700">{aiError}</p>
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            Click "Get AI Analysis" for an AI-powered assessment of this node's resource usage, configuration drift, and recent alerts — with ranked actionable recommendations.
          </p>
        )}
      </div>
    </div>
  )
})
