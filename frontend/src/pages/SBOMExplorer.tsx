import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { sbomApi } from '../api/sbom'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { formatDistanceToNow } from 'date-fns'

export function SBOMExplorer() {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  function handleInput(value: string) {
    setQ(value)
    setBrowsing(false)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQ(value), 300)
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['sbom-search', debouncedQ],
    queryFn: () => sbomApi.search(debouncedQ),
    enabled: !browsing && debouncedQ.length >= 3,
    staleTime: 60_000,
  })

  const { data: browseData, isLoading: browseLoading, isError: browseError, refetch: browseRefetch } = useQuery({
    queryKey: ['sbom-browse'],
    queryFn: () => sbomApi.browse(),
    enabled: browsing,
    staleTime: 60_000,
  })

  const displayData = browsing ? browseData : data
  const displayLoading = browsing ? browseLoading : isLoading
  const displayError = browsing ? browseError : isError
  const displayRefetch = browsing ? browseRefetch : refetch

  const showResults = browsing || debouncedQ.length >= 3

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">SBOM Explorer</h1>
      <div className="max-w-lg space-y-2">
        <div className="flex gap-2">
          <input
            type="search"
            placeholder="Search packages fleet-wide (min 3 chars)…"
            value={q}
            onChange={(e) => handleInput(e.target.value)}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:ring-2 focus:ring-brand-500"
          />
          <button
            onClick={() => { setQ(''); setDebouncedQ(''); setBrowsing(true) }}
            className={`px-4 py-2 text-sm font-medium rounded-lg border transition-colors ${
              browsing
                ? 'bg-brand-600 text-white border-brand-600'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
            }`}
          >
            Browse all
          </button>
        </div>
        {q.length > 0 && q.length < 3 && !browsing && (
          <p className="text-xs text-gray-500">Type at least 3 characters to search</p>
        )}
      </div>
      {showResults && (
        <div className="bg-white rounded-lg shadow-xs border border-gray-200 overflow-hidden">
          {displayLoading ? <Skeleton rows={8} /> : displayError ? (
            <ErrorState message="Failed to load packages" retry={displayRefetch} />
          ) : displayData && displayData.length === 0 ? (
            <p className="p-8 text-center text-gray-500 text-sm">
              {browsing ? 'No packages found in the fleet.' : `No packages found matching "${debouncedQ}"`}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Package</th>
                  <th className="px-4 py-3">Version</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Node</th>
                  <th className="px-4 py-3">Scanned</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {displayData?.map((r, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs font-medium">{r.name}</td>
                    <td className="px-4 py-3 text-gray-600">{r.version ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-600">{r.component_type ?? '—'}</td>
                    <td className="px-4 py-3">
                      <Link to={`/nodes/${r.node_id}`} className="text-brand-600 hover:underline">{r.hostname}</Link>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {formatDistanceToNow(new Date(r.scanned_at), { addSuffix: true })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
