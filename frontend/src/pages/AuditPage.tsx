import { useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi } from '../api/audit'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'

function actionBadgeClass(action: string): string {
  if (action.endsWith('.create')) return 'bg-green-100 text-green-700'
  if (action.endsWith('.delete') || action.includes('.block') || action.includes('security')) return 'bg-red-100 text-red-700'
  if (action.endsWith('.update')) return 'bg-blue-100 text-blue-700'
  if (action === 'auth.login') return 'bg-gray-100 text-gray-600'
  return 'bg-gray-100 text-gray-600'
}

export function AuditPage() {
  const [page, setPage] = useState(1)
  const [actorFilter, setActorFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [debouncedActor, setDebouncedActor] = useState('')
  const [debouncedAction, setDebouncedAction] = useState('')
  const actorTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const actionTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  function handleActor(value: string) {
    setActorFilter(value)
    clearTimeout(actorTimer.current)
    actorTimer.current = setTimeout(() => { setDebouncedActor(value); setPage(1) }, 400)
  }

  function handleAction(value: string) {
    setActionFilter(value)
    clearTimeout(actionTimer.current)
    actionTimer.current = setTimeout(() => { setDebouncedAction(value); setPage(1) }, 400)
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit', debouncedActor, debouncedAction, page],
    queryFn: () => auditApi.list({
      actor: debouncedActor || undefined,
      action: debouncedAction || undefined,
      page,
      per_page: 50,
    }),
    staleTime: 15_000,
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>

      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="search"
          placeholder="Filter by actor email…"
          value={actorFilter}
          onChange={(e) => handleActor(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-56"
        />
        <input
          type="search"
          placeholder="Filter by action…"
          value={actionFilter}
          onChange={(e) => handleAction(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-48"
        />
        {data && <span className="text-sm text-gray-500">{data.total} events</span>}
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={12} />
        ) : isError ? (
          <ErrorState message="Failed to load audit log" retry={refetch} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Resource Type</th>
                  <th className="px-4 py-3">Resource ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                      No audit events found
                    </td>
                  </tr>
                )}
                {data?.items.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                      {formatDistanceToNow(new Date(e.event_at), { addSuffix: true })}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700 max-w-[180px] truncate">
                      {e.actor}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium font-mono ${actionBadgeClass(e.action)}`}>
                        {e.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{e.resource_type ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                      {e.resource_id ? e.resource_id.slice(0, 8) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && (
              <Pagination
                page={page}
                total={data.total}
                perPage={data.per_page}
                onPage={setPage}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}
