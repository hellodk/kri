import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { driftApi, type DriftPackageState } from '../api/drift'
import { fleetApi } from '../api/fleet'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

// Cell colour by status
const STATUS_CELL: Record<string, string> = {
  ok:      'bg-emerald-50 text-emerald-800',
  missing: 'bg-red-50 text-red-700',
  mismatch:'bg-amber-50 text-amber-700',
  extra:   'bg-blue-50 text-blue-700',
  unknown: 'bg-gray-50 text-gray-400',
}

const STATUS_LABEL: Record<string, string> = {
  ok:      'ok',
  missing: 'missing',
  mismatch:'mismatch',
  extra:   'extra',
  unknown: '—',
}

function CellContent({ state }: { state: DriftPackageState }) {
  const cls = STATUS_CELL[state.status] ?? STATUS_CELL.unknown
  const label = state.installed ?? state.expected ?? '—'
  const badge = STATUS_LABEL[state.status]

  return (
    <td className={`px-3 py-2 text-xs font-mono ${cls} border-r border-gray-100 last:border-r-0`}>
      <div className="flex flex-col gap-0.5">
        <span>{label}</span>
        {state.status !== 'ok' && state.status !== 'unknown' && (
          <span className="text-[10px] opacity-60 capitalize">{badge}</span>
        )}
      </div>
    </td>
  )
}

export function DriftComparePage() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [driftedOnly, setDriftedOnly] = useState(true)

  // Load all nodes for the picker
  const { data: nodesData, isLoading: nodesLoading } = useQuery({
    queryKey: ['fleet-nodes-all'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    staleTime: 60_000,
  })

  const nodes = nodesData?.items ?? []

  const filteredNodes = useMemo(
    () =>
      nodes.filter((n) =>
        !search || (n.hostname ?? n.id).toLowerCase().includes(search.toLowerCase()),
      ),
    [nodes, search],
  )

  const toggleNode = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectedList = Array.from(selectedIds)

  const {
    data: compareData,
    isLoading: compareLoading,
    isError: compareError,
    refetch: retryCompare,
  } = useQuery({
    queryKey: ['drift-compare', selectedList.join(',')],
    queryFn: () => driftApi.compare(selectedList),
    enabled: selectedList.length >= 1,
    staleTime: 60_000,
  })

  // Filter packages: only show drifted rows when toggle is on
  const displayedPackages = useMemo(() => {
    if (!compareData) return []
    if (!driftedOnly) return compareData.packages
    return compareData.packages.filter((pkg) =>
      Object.values(pkg.states).some((s) => s.status !== 'ok' && s.status !== 'unknown'),
    )
  }, [compareData, driftedOnly])

  // Export as CSV
  const exportCSV = () => {
    if (!compareData) return
    const nodeOrder = compareData.nodes.map((n) => n.id)
    const headers = ['Package', ...compareData.nodes.map((n) => n.hostname ?? n.id)]
    const rows = compareData.packages.map((pkg) => [
      pkg.name,
      ...nodeOrder.map((nid) => {
        const s = pkg.states[nid]
        if (!s) return ''
        return s.installed ?? s.expected ?? s.status
      }),
    ])
    const csv = [headers, ...rows]
      .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `drift-compare-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    window.URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Drift Comparison</h1>
        {selectedList.length > 0 && compareData && (
          <button
            onClick={exportCSV}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 flex items-center gap-1.5"
          >
            Export CSV
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Node picker */}
        <div className="md:col-span-1 bg-white rounded-lg border border-gray-200 p-4 space-y-3 self-start">
          <h2 className="text-sm font-semibold text-gray-700">Select Nodes</h2>
          <input
            type="search"
            placeholder="Search by hostname…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-hidden focus:ring-2 focus:ring-brand-400"
          />
          {nodesLoading ? (
            <Skeleton rows={6} />
          ) : (
            <ul className="space-y-1 max-h-96 overflow-y-auto">
              {filteredNodes.map((n) => (
                <li key={n.id}>
                  <label className="flex items-center gap-2 cursor-pointer rounded px-2 py-1.5 hover:bg-gray-50 select-none">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(n.id)}
                      onChange={() => toggleNode(n.id)}
                      className="rounded border-gray-300 text-brand-600"
                    />
                    <span className="flex-1 text-sm font-medium text-gray-800 truncate">
                      {n.hostname ?? n.id}
                    </span>
                    <DriftBadge score={n.drift_score} />
                  </label>
                </li>
              ))}
              {filteredNodes.length === 0 && (
                <li className="text-xs text-gray-400 px-2 py-2">No nodes match.</li>
              )}
            </ul>
          )}
          {selectedList.length > 0 && (
            <p className="text-xs text-gray-500">
              {selectedList.length} node{selectedList.length !== 1 ? 's' : ''} selected
            </p>
          )}
        </div>

        {/* Comparison matrix */}
        <div className="md:col-span-2 space-y-4">
          {selectedList.length === 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center text-gray-500 text-sm">
              Select one or more nodes on the left to compare drift.
            </div>
          )}

          {selectedList.length > 0 && compareLoading && <Skeleton rows={10} />}
          {selectedList.length > 0 && compareError && (
            <ErrorState message="Failed to load comparison data" retry={retryCompare} />
          )}

          {compareData && (
            <>
              {/* Summary */}
              <div className="flex items-center gap-4 flex-wrap text-sm text-gray-600">
                <span>{compareData.summary.total_packages} total packages</span>
                <span className="text-gray-300">|</span>
                <span>{compareData.summary.drifted_nodes} node{compareData.summary.drifted_nodes !== 1 ? 's' : ''} with drift</span>
                <div className="ml-auto flex items-center gap-2">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={driftedOnly}
                      onChange={(e) => setDriftedOnly(e.target.checked)}
                      className="rounded border-gray-300 text-brand-600"
                    />
                    <span className="text-xs">Show drifted only</span>
                  </label>
                </div>
              </div>

              {/* Matrix table */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase sticky left-0 bg-gray-50 z-10 border-r border-gray-200">
                        Package
                      </th>
                      {compareData.nodes.map((n) => (
                        <th
                          key={n.id}
                          className="px-3 py-2 text-xs font-medium text-gray-500 uppercase whitespace-nowrap min-w-[130px]"
                        >
                          <div className="flex flex-col items-start gap-1">
                            <span className="truncate max-w-[120px]">{n.hostname ?? n.id.slice(0, 8)}</span>
                            <DriftBadge score={n.drift_score} />
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {displayedPackages.length === 0 ? (
                      <tr>
                        <td
                          colSpan={compareData.nodes.length + 1}
                          className="px-4 py-8 text-center text-sm text-gray-400"
                        >
                          {driftedOnly
                            ? 'No drift detected — all selected nodes are in compliance.'
                            : 'No package data available.'}
                        </td>
                      </tr>
                    ) : (
                      displayedPackages.map((pkg) => (
                        <tr key={pkg.name} className="hover:bg-gray-50/60">
                          <td className="px-4 py-2 font-mono text-xs font-medium text-gray-900 sticky left-0 bg-white border-r border-gray-100 z-10">
                            {pkg.name}
                          </td>
                          {compareData.nodes.map((n) => (
                            <CellContent
                              key={n.id}
                              state={
                                pkg.states[n.id] ?? {
                                  installed: null,
                                  expected: null,
                                  status: 'unknown',
                                }
                              }
                            />
                          ))}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Legend */}
              <div className="flex items-center gap-4 text-xs text-gray-500 flex-wrap">
                <span className="font-medium">Legend:</span>
                {Object.entries(STATUS_CELL).filter(([k]) => k !== 'unknown').map(([status, cls]) => (
                  <span key={status} className={`px-2 py-0.5 rounded ${cls} capitalize`}>
                    {status}
                  </span>
                ))}
                <span className="px-2 py-0.5 rounded bg-gray-50 text-gray-400">unknown</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
