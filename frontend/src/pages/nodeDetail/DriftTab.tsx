import { memo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { driftApi } from '../../api/drift'
import { formatIST, formatChartDate } from '../../utils/time'
import { formatGrainKey } from '../DriftExplorer'

export const DriftTab = memo(function DriftTab({ nodeId }: { nodeId: string }) {
  const qc = useQueryClient()

  const { data: latestDrift } = useQuery({
    queryKey: ['drift-latest', nodeId],
    queryFn: () => driftApi.latest(nodeId),
    staleTime: 60_000,
    enabled: !!nodeId,
  })

  const { data: driftHistory } = useQuery({
    queryKey: ['drift-history', nodeId],
    queryFn: () => driftApi.history(nodeId, { per_page: 30 }),
    staleTime: 60_000,
    enabled: !!nodeId,
  })

  const computeMutation = useMutation({
    mutationFn: () => driftApi.compute(nodeId),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['drift-latest', nodeId] }), 3000)
    },
  })

  const chartData = driftHistory?.items
    .slice()
    .reverse()
    .map((d) => ({
      date: d.computed_at ? formatChartDate(d.computed_at) : '',
      score: d.drift_score,
    }))

  return (
    <div role="tabpanel" id="tabpanel-drift" aria-labelledby="tab-drift" className="space-y-4">
      <div className="flex justify-end">
        <button
          onClick={() => computeMutation.mutate()}
          disabled={computeMutation.isPending}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50"
        >
          {computeMutation.isPending ? 'Queuing…' : 'Trigger Drift Compute'}
        </button>
      </div>

      {/* No drift record yet — but check for no baseline first */}
      {!latestDrift && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
          No baseline assigned — create one in{' '}
          <a href="/baselines" className="underline font-medium">Baselines</a>{' '}
          to start tracking drift.
        </div>
      )}

      {latestDrift && (() => {
        const missing = latestDrift.missing_packages ?? []
        const extra = latestDrift.extra_packages ?? []
        const mismatches = latestDrift.version_mismatches ?? []
        const totalDrifted = missing.length + mismatches.length + extra.length
        const isClean = latestDrift.drift_score === 0 && latestDrift.baseline_name != null

        return (
          <div className="space-y-4">
            {/* Score header */}
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <div className="flex items-center gap-6 flex-wrap">
                <div>
                  <p className="text-xs text-gray-500 uppercase">Drift Score</p>
                  <p className="text-3xl font-bold text-gray-900">{latestDrift.drift_score}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase">Severity</p>
                  <p className="text-lg font-semibold capitalize">{latestDrift.severity}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase">Baseline</p>
                  <p className="text-sm">{latestDrift.baseline_name ?? '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase">Computed</p>
                  <p className="text-sm">{formatIST(latestDrift.computed_at)}</p>
                </div>
              </div>
            </div>

            {/* Compliance banner or summary chips */}
            {isClean ? (
              <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-emerald-800 text-sm font-medium">
                <span className="text-base">✓</span>
                <span>In compliance — all packages match the baseline.</span>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-sm text-gray-600 font-medium">{totalDrifted} packages drifted</span>
                {missing.length > 0 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 border border-red-200">
                    <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                    {missing.length} missing
                  </span>
                )}
                {mismatches.length > 0 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700 border border-amber-200">
                    <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
                    {mismatches.length} version mismatch{mismatches.length !== 1 ? 'es' : ''}
                  </span>
                )}
                {extra.length > 0 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 border border-blue-200">
                    <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />
                    {extra.length} extra
                  </span>
                )}
              </div>
            )}

            {/* Missing packages */}
            {missing.length > 0 && (
              <div className="bg-white rounded-lg border border-red-200 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2 bg-red-50 border-b border-red-200">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
                  <h4 className="text-sm font-semibold text-red-800">Missing Packages</h4>
                  <span className="ml-auto text-xs text-red-600">Expected by baseline but not installed</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                      <th scope="col" className="px-4 py-2 text-left font-medium">Package</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Expected Version</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Severity Hint</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {missing.map((pkg) => (
                      <tr key={pkg.name} className="hover:bg-red-50/30">
                        <td className="px-4 py-2 font-mono font-medium text-gray-900">{pkg.name}</td>
                        <td className="px-4 py-2 font-mono text-gray-600">{pkg.required_version ?? '—'}</td>
                        <td className="px-4 py-2">
                          <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">required</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Version mismatches */}
            {mismatches.length > 0 && (
              <div className="bg-white rounded-lg border border-amber-200 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                  <h4 className="text-sm font-semibold text-amber-800">Version Mismatches</h4>
                  <span className="ml-auto text-xs text-amber-600">Package present but wrong version</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                      <th scope="col" className="px-4 py-2 text-left font-medium">Package</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Installed</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Expected</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Δ</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {mismatches.map((pkg) => (
                      <tr key={pkg.name} className="hover:bg-amber-50/30">
                        <td className="px-4 py-2 font-mono font-medium text-gray-900">{pkg.name}</td>
                        <td className="px-4 py-2 font-mono text-amber-700">{pkg.actual ?? '—'}</td>
                        <td className="px-4 py-2 font-mono text-gray-600">{pkg.expected ?? '—'}</td>
                        <td className="px-4 py-2 text-xs text-gray-500 font-mono">
                          {pkg.actual && pkg.expected ? `${pkg.actual} → ${pkg.expected}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Extra packages */}
            {extra.length > 0 && (
              <div className="bg-white rounded-lg border border-blue-200 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2 bg-blue-50 border-b border-blue-200">
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                  <h4 className="text-sm font-semibold text-blue-800">Extra Packages</h4>
                  <span className="ml-auto text-xs text-blue-600">Installed but not in baseline</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                      <th scope="col" className="px-4 py-2 text-left font-medium">Package</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Installed Version</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Note</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {extra.map((pkg) => (
                      <tr key={pkg.name} className="hover:bg-blue-50/30">
                        <td className="px-4 py-2 font-mono font-medium text-gray-900">{pkg.name}</td>
                        <td className="px-4 py-2 font-mono text-gray-600">{pkg.installed_version ?? '—'}</td>
                        <td className="px-4 py-2 text-xs text-gray-600">not in baseline</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Service drift */}
            {(latestDrift.service_drift ?? []).length > 0 && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 border-b border-gray-200">
                  <h4 className="text-sm font-semibold text-gray-700">Service Drift</h4>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                      <th scope="col" className="px-4 py-2 text-left font-medium">Service</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Expected</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Actual</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {latestDrift.service_drift.map((svc) => (
                      <tr key={svc.service ?? svc.name} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-medium text-gray-900" title={svc.service ?? svc.name}>
                          {formatGrainKey(svc.service ?? svc.name ?? '')}
                        </td>
                        <td className="px-4 py-2 text-gray-600">{svc.expected}</td>
                        <td className="px-4 py-2 text-red-600">{svc.actual}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Config / Grain drift */}
            {(latestDrift.config_drift as Array<{ key: string; expected: unknown; actual: unknown }> ?? []).length > 0 && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 border-b border-gray-200">
                  <h4 className="text-sm font-semibold text-gray-700">Config / Grain Drift</h4>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                      <th scope="col" className="px-4 py-2 text-left font-medium">Key</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Expected</th>
                      <th scope="col" className="px-4 py-2 text-left font-medium">Actual</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {(latestDrift.config_drift as Array<{ key: string; expected: unknown; actual: unknown }>).map((item) => (
                      <tr key={item.key} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-medium text-gray-900" title={item.key}>
                          {formatGrainKey(item.key)}
                        </td>
                        <td className="px-4 py-2 font-mono text-xs text-gray-600">
                          {String(item.expected ?? '—')}
                        </td>
                        <td className="px-4 py-2 font-mono text-xs text-red-600">
                          {String(item.actual ?? '—')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })()}

      {chartData && chartData.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h4 className="text-sm font-medium text-gray-700 mb-3">Drift History (30 days)</h4>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="score" stroke="#2563eb" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
})
