import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { saltKeysApi } from '../api/saltKeys'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'

const STATUS_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  accepted: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
  pending:  { bg: 'bg-amber-50',   text: 'text-amber-700',   border: 'border-amber-200' },
  rejected: { bg: 'bg-red-50',     text: 'text-red-700',     border: 'border-red-200' },
  denied:   { bg: 'bg-gray-50',    text: 'text-gray-600',    border: 'border-gray-200' },
}

export function SaltKeysPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const { data: keys, isLoading } = useQuery({
    queryKey: ['salt-keys'],
    queryFn: saltKeysApi.list,
    refetchInterval: 15_000,
  })

  const acceptMut = useMutation({
    mutationFn: (id: string) => saltKeysApi.accept(id),
    onSuccess: (_, id) => { toast(`Accepted: ${id}`, 'success'); qc.invalidateQueries({ queryKey: ['salt-keys'] }) },
    onError: () => toast('Failed to accept key', 'error'),
  })

  const rejectMut = useMutation({
    mutationFn: (id: string) => saltKeysApi.reject(id),
    onSuccess: (_, id) => { toast(`Rejected: ${id}`, 'info'); qc.invalidateQueries({ queryKey: ['salt-keys'] }) },
    onError: () => toast('Failed to reject key', 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => saltKeysApi.delete(id),
    onSuccess: (_, id) => { toast(`Deleted: ${id}`, 'info'); qc.invalidateQueries({ queryKey: ['salt-keys'] }) },
    onError: () => toast('Failed to delete key', 'error'),
  })

  const sections: Array<{ status: keyof typeof STATUS_STYLE; label: string; items: string[] }> = [
    { status: 'pending',  label: 'Pending Approval',  items: keys?.pending  ?? [] },
    { status: 'accepted', label: 'Accepted',           items: keys?.accepted ?? [] },
    { status: 'rejected', label: 'Rejected',           items: keys?.rejected ?? [] },
    { status: 'denied',   label: 'Denied',             items: keys?.denied   ?? [] },
  ]

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Minion Keys</h1>
          <p className="text-sm text-gray-500 mt-0.5">Salt minion key approval — auto-accept is disabled</p>
        </div>
        {(keys?.pending_count ?? 0) > 0 && (
          <span className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-100 text-amber-800 text-sm font-medium rounded-full border border-amber-300 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
            {keys!.pending_count} pending
          </span>
        )}
      </div>

      {keys?.degraded && (
        <div className="flex items-start gap-3 p-4 rounded-lg border border-red-200 bg-red-50">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="shrink-0 mt-0.5" aria-hidden="true">
            <path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm0 4a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 7a1 1 0 110 2 1 1 0 010-2z" fill="#DC2626"/>
          </svg>
          <div>
            <p className="text-sm font-semibold text-red-800">Salt PKI directory unavailable</p>
            <p className="text-sm text-red-700 mt-0.5">
              {keys.degraded_reason ?? 'Cannot read Salt key directory — check container mount and permissions.'}
            </p>
            <p className="text-xs text-red-600 mt-1">
              Key list may be incomplete or empty. Resolve the permission issue and reload.
            </p>
          </div>
        </div>
      )}

      {isLoading ? (
        <Skeleton rows={6} />
      ) : (
        sections.map(({ status, label, items }) =>
          items.length === 0 ? null : (
            <div key={status} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
              <div className={`px-4 py-2.5 border-b ${STATUS_STYLE[status].border} ${STATUS_STYLE[status].bg} flex items-center justify-between`}>
                <span className={`text-sm font-semibold ${STATUS_STYLE[status].text}`}>{label}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full border ${STATUS_STYLE[status].border} ${STATUS_STYLE[status].bg} ${STATUS_STYLE[status].text}`}>
                  {items.length}
                </span>
              </div>
              <ul className="divide-y divide-gray-100">
                {items.map((id) => (
                  <li key={id} className="flex items-center justify-between px-4 py-3 hover:bg-gray-50">
                    <span className="font-mono text-sm text-gray-800">{id}</span>
                    <div className="flex items-center gap-2">
                      {status === 'pending' && (
                        <>
                          <button
                            onClick={() => acceptMut.mutate(id)}
                            disabled={acceptMut.isPending}
                            className="text-xs px-3 py-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                          >
                            Accept
                          </button>
                          <button
                            onClick={() => rejectMut.mutate(id)}
                            disabled={rejectMut.isPending}
                            className="text-xs px-3 py-1.5 rounded bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-50"
                          >
                            Reject
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => deleteMut.mutate(id)}
                        disabled={deleteMut.isPending}
                        className="text-xs px-2 py-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
                        title="Delete key"
                      >
                        ✕
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )
        )
      )}

      {!isLoading && keys?.degraded && keys.accepted.length === 0 && keys.pending.length === 0 && keys.rejected.length === 0 && keys.denied.length === 0 && (
        <div className="text-center py-8 text-gray-500 text-sm">
          No keys available — Salt PKI directory is inaccessible.
        </div>
      )}

      {!isLoading && !keys?.degraded && sections.every((s) => s.items.length === 0) && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-3xl mb-2">🔑</p>
          <p className="text-sm">No minion keys yet.</p>
          <p className="text-xs mt-1">Bootstrap a node to see its key appear here.</p>
        </div>
      )}
    </div>
  )
}
