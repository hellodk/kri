import { memo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { sbomApi } from '../../api/sbom'
import { api } from '../../api/client'
import { formatIST } from '../../utils/time'
import { Pagination } from '../../components/Pagination'
import { useToastStore } from '../../stores/toastStore'

export const SbomTab = memo(function SbomTab({ nodeId }: { nodeId: string }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [sbomFilter, setSbomFilter] = useState('')
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null)
  const [triggeringScan, setTriggeringScan] = useState(false)
  const [compPage, setCompPage] = useState(1)

  const { data: sbomScanHistory } = useQuery({
    queryKey: ['sbom-scans', nodeId],
    queryFn: () => sbomApi.scans(nodeId, { per_page: 50 }),
    staleTime: 300_000,
    enabled: !!nodeId,
  })

  const activeScanId = selectedScanId ?? sbomScanHistory?.items[0]?.id
  const activeScan = sbomScanHistory?.items.find((s) => s.id === activeScanId) ?? sbomScanHistory?.items[0]

  const { data: components } = useQuery({
    queryKey: ['sbom-components', nodeId, activeScanId, compPage],
    queryFn: () => sbomApi.components(nodeId, activeScanId!, { page: compPage, per_page: 200 }),
    staleTime: 300_000,
    enabled: !!activeScanId,
  })

  const { data: nodeVulns } = useQuery({
    queryKey: ['node-vulns', nodeId],
    queryFn: () => api.get<{ vulnerabilities: Array<{ package_name: string; severity: string; cve_id: string }> }>(`/api/v1/security/nodes/${nodeId}`),
    staleTime: 300_000,
    enabled: !!nodeId,
  })

  const vulnsByPkg = (nodeVulns?.vulnerabilities ?? []).reduce<Record<string, string[]>>((acc, v) => {
    if (!acc[v.package_name]) acc[v.package_name] = []
    acc[v.package_name].push(v.severity)
    return acc
  }, {})

  return (
    <div role="tabpanel" id="tabpanel-sbom" aria-labelledby="tab-sbom" className="space-y-4">
      {/* Header: scan selector + trigger */}
      <div className="flex items-center gap-3 flex-wrap">
        {(sbomScanHistory?.items.length ?? 0) > 0 ? (
          <select
            className="text-sm border border-gray-300 rounded px-2 py-1 bg-white"
            value={activeScanId ?? ''}
            onChange={(e) => { setSelectedScanId(e.target.value); setCompPage(1) }}
          >
            {sbomScanHistory!.items.map((s, i) => (
              <option key={s.id} value={s.id}>
                {formatIST(s.scanned_at)}{i === 0 ? ' (latest)' : ''}
              </option>
            ))}
          </select>
        ) : null}
        <button
          className="ml-auto text-sm px-3 py-1.5 rounded bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          disabled={triggeringScan}
          onClick={async () => {
            setTriggeringScan(true)
            try {
              await api.post(`/api/v1/security/scan/${nodeId}?scanner=trivy`, {})
              toast('SBOM scan queued', 'success')
              setTimeout(() => qc.invalidateQueries({ queryKey: ['sbom-scans', nodeId] }), 5000)
            } catch {
              toast('Failed to queue scan', 'error')
            } finally {
              setTriggeringScan(false)
            }
          }}
        >
          {triggeringScan ? 'Queuing…' : '⟳ Scan now'}
        </button>
      </div>

      {activeScan ? (
        <>
          {/* Scan metadata */}
          <div className="bg-white rounded-lg border border-gray-200 p-4 flex gap-8 text-sm">
            <div>
              <p className="text-gray-500">Scanned</p>
              <p className="font-medium">{formatIST(activeScan.scanned_at)}</p>
            </div>
            <div>
              <p className="text-gray-500">Format</p>
              <p className="font-medium">{activeScan.format ?? 'cyclonedx'}</p>
            </div>
            <div>
              <p className="text-gray-500">Components</p>
              <p className="font-medium">{activeScan.component_count ?? '—'}</p>
            </div>
            {Object.keys(vulnsByPkg).length > 0 && (
              <div>
                <p className="text-gray-500">With CVEs</p>
                <p className="font-medium text-red-600">{Object.keys(vulnsByPkg).length}</p>
              </div>
            )}
          </div>

          {/* Search */}
          <input
            type="search"
            placeholder="Filter packages…"
            value={sbomFilter}
            onChange={(e) => { setSbomFilter(e.target.value); setCompPage(1) }}
            className="w-full text-sm border border-gray-300 rounded px-3 py-1.5 focus:outline-hidden focus:ring-2 focus:ring-brand-500"
          />

          {/* Component table */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                  <th scope="col" className="px-4 py-3">Name</th>
                  <th scope="col" className="px-4 py-3">Version</th>
                  <th scope="col" className="px-4 py-3">Type</th>
                  <th scope="col" className="px-4 py-3">Licenses</th>
                  <th scope="col" className="px-4 py-3">CVEs</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(components?.items ?? [])
                  .filter((c) => !sbomFilter || c.name.toLowerCase().includes(sbomFilter.toLowerCase()))
                  .map((c) => {
                    const sevs = vulnsByPkg[c.name] ?? []
                    const hasCrit = sevs.includes('CRITICAL')
                    const hasHigh = sevs.includes('HIGH')
                    return (
                      <tr key={c.id} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-mono text-xs">
                          {c.purl ? (
                            <span title={c.purl}>{c.name}</span>
                          ) : c.name}
                        </td>
                        <td className="px-4 py-2 text-gray-600">{c.version ?? '—'}</td>
                        <td className="px-4 py-2 text-gray-600">{c.component_type ?? '—'}</td>
                        <td className="px-4 py-2 text-gray-600">{c.licenses.join(', ') || '—'}</td>
                        <td className="px-4 py-2">
                          {sevs.length > 0 ? (
                            <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                              hasCrit ? 'bg-red-100 text-red-700' :
                              hasHigh ? 'bg-orange-100 text-orange-700' :
                              'bg-yellow-100 text-yellow-700'
                            }`}>
                              {sevs.length} {hasCrit ? 'CRITICAL' : hasHigh ? 'HIGH' : 'MEDIUM/LOW'}
                            </span>
                          ) : (
                            <span className="text-gray-300 text-xs">—</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
            {components && !sbomFilter && (
              <Pagination page={compPage} total={components.total} perPage={components.per_page} onPage={setCompPage} />
            )}
          </div>
        </>
      ) : (
        <div className="text-center py-12 text-gray-500 text-sm">
          <p className="text-2xl mb-2">📦</p>
          <p>No SBOM scans yet.</p>
          <p className="text-xs mt-1">Click "Scan now" to trigger a Trivy scan.</p>
        </div>
      )}
    </div>
  )
})
