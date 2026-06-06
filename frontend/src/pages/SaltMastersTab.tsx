/**
 * Salt Masters settings tab — issue #521, epic #523.
 *
 * READ-ONLY view of all configured salt-masters.
 * Create/edit deferred to #522.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { saltMastersApi } from '../api/saltMasters'
import { saltMasterBadge } from '../lib/saltMasterHelpers'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

function formatIst(isoString: string): string {
  return (
    new Date(isoString).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }) + ' IST'
  )
}

function relativeTime(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return `${Math.floor(diffHr / 24)}d ago`
}

const checkStatusPill = (status: string) => {
  switch (status) {
    case 'pass':
      return 'bg-emerald-100 text-emerald-800 border border-emerald-200'
    case 'fail':
      return 'bg-red-100 text-red-800 border border-red-200'
    case 'warn':
      return 'bg-amber-100 text-amber-800 border border-amber-200'
    default:
      return 'bg-gray-100 text-gray-700 border border-gray-200'
  }
}

export function SaltMastersTab() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const { data: masters, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => saltMastersApi.test(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      toast('Connection test completed', 'success')
    },
    onError: (err: Error) => {
      toast(`Test failed: ${err.message}`, 'error')
    },
  })

  if (isLoading) return <Skeleton rows={4} />

  if (isError) {
    return (
      <ErrorState
        message={(error as Error)?.message ?? 'Failed to load salt masters'}
        retry={() => refetch()}
      />
    )
  }

  if (!masters || masters.length === 0) {
    return (
      <div className="py-12 text-center">
        <div className="mx-auto w-12 h-12 mb-4 rounded-full bg-gray-100 flex items-center justify-center">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-gray-400" aria-hidden="true">
            <rect x="2" y="3" width="20" height="14" rx="2" />
            <path d="M8 21h8M12 17v4" />
          </svg>
        </div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">No salt-master configured</h3>
        <p className="text-sm text-gray-600">Create/edit support is coming in a follow-up release (#522).</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Salt Masters</h2>
        <p className="text-sm text-gray-600 mt-1">
          Configured Salt API endpoints. Create and edit support coming in #522.
        </p>
      </div>

      <div className="space-y-4">
        {masters.map((master) => {
          const badge = saltMasterBadge(master.status)
          const isPending = testMutation.isPending && testMutation.variables === master.id

          const checks = Array.isArray(master.checks)
            ? master.checks as Array<{ check: string; status: string; detail: string; latency_ms: number }>
            : master.checks
              ? (Object.values(master.checks) as Array<{ check: string; status: string; detail: string; latency_ms: number }>)
              : []

          return (
            <div
              key={master.id}
              className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden"
            >
              {/* Header row */}
              <div className="px-5 py-4 flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-gray-900 truncate">
                      {master.name}
                    </span>
                    {master.is_default && (
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-brand-100 text-brand-700 border border-brand-200">
                        Default
                      </span>
                    )}
                    {!master.enabled && (
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-600 border border-gray-200">
                        Disabled
                      </span>
                    )}
                    <span
                      className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${badge.bgClass} ${badge.textClass}`}
                    >
                      {badge.label}
                    </span>
                  </div>
                  <div className="mt-1 text-sm text-gray-600 font-mono truncate">
                    {master.address}
                    {master.api_url && (
                      <span className="ml-2 text-gray-400 non-mono font-sans">
                        · {master.api_url}
                      </span>
                    )}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => testMutation.mutate(master.id)}
                  disabled={isPending}
                  className="shrink-0 px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
                  title="Run a live connectivity probe against this salt-master"
                >
                  {isPending ? 'Testing…' : 'Test connection'}
                </button>
              </div>

              {/* Meta row */}
              <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex flex-wrap gap-x-6 gap-y-1.5 text-xs text-gray-600">
                <span>
                  <span className="font-medium text-gray-700">Mode:</span>{' '}
                  {master.control_mode}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Token delivery:</span>{' '}
                  {master.token_delivery}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Publish port:</span>{' '}
                  {master.publish_port}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Return port:</span>{' '}
                  {master.ret_port}
                </span>
                {master.api_user && (
                  <span>
                    <span className="font-medium text-gray-700">API user:</span>{' '}
                    {master.api_user}
                  </span>
                )}
                {master.api_eauth && (
                  <span>
                    <span className="font-medium text-gray-700">eAuth:</span>{' '}
                    {master.api_eauth}
                  </span>
                )}
                <span>
                  <span className="font-medium text-gray-700">Last checked:</span>{' '}
                  {master.last_checked_at ? (
                    <span title={relativeTime(master.last_checked_at)}>
                      {formatIst(master.last_checked_at)}
                    </span>
                  ) : (
                    <span className="text-gray-500 italic">never checked</span>
                  )}
                </span>
              </div>

              {/* Last error */}
              {master.last_error && (
                <div className="px-5 py-3 bg-red-50 border-t border-red-100 text-xs text-red-700 font-mono">
                  {master.last_error}
                </div>
              )}

              {/* Checks table */}
              {checks.length > 0 && (
                <div className="border-t border-gray-100">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-100">
                        <th className="px-5 py-2 text-left font-semibold text-gray-700">Check</th>
                        <th className="px-5 py-2 text-left font-semibold text-gray-700">Status</th>
                        <th className="px-5 py-2 text-left font-semibold text-gray-700">Detail</th>
                        <th className="px-5 py-2 text-right font-semibold text-gray-700">Latency</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {checks.map((chk, i) => (
                        <tr key={i} className="hover:bg-gray-50">
                          <td className="px-5 py-2 font-mono text-gray-800">{chk.check}</td>
                          <td className="px-5 py-2">
                            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${checkStatusPill(chk.status)}`}>
                              {chk.status}
                            </span>
                          </td>
                          <td className="px-5 py-2 text-gray-600">{chk.detail}</td>
                          <td className="px-5 py-2 text-right font-mono text-gray-600">
                            {chk.latency_ms != null ? `${chk.latency_ms}ms` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
