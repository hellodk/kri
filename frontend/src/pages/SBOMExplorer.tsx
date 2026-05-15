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
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  function handleInput(value: string) {
    setQ(value)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQ(value), 300)
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['sbom-search', debouncedQ],
    queryFn: () => sbomApi.search(debouncedQ),
    enabled: debouncedQ.length >= 3,
    staleTime: 60_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">SBOM Explorer</h1>
      <div className="max-w-lg">
        <input
          type="search"
          placeholder="Search packages fleet-wide (min 3 chars)…"
          value={q}
          onChange={(e) => handleInput(e.target.value)}
          className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
        {q.length > 0 && q.length < 3 && (
          <p className="mt-1 text-xs text-gray-500">Type at least 3 characters to search</p>
        )}
      </div>
      {debouncedQ.length >= 3 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          {isLoading ? <Skeleton rows={8} /> : isError ? (
            <ErrorState message="Search failed" retry={refetch} />
          ) : data && data.length === 0 ? (
            <p className="p-8 text-center text-gray-500 text-sm">No packages found matching "{debouncedQ}"</p>
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
                {data?.map((r, i) => (
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
