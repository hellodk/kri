import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { auditApi } from '../api/audit'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'
import { formatLocalDateTime } from '../utils/time'

const RESOURCE_TYPES = ['node', 'group', 'user', 'setting', 'playbook']

const PRESETS: { label: string; minutes: number }[] = [
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
  { label: '7d', minutes: 10080 },
  { label: '30d', minutes: 43200 },
]

function actionBadgeClass(action: string): string {
  if (action.endsWith('.create')) return 'bg-green-100 text-green-700'
  if (action.endsWith('.delete') || action.includes('.block') || action.includes('security')) return 'bg-red-100 text-red-700'
  if (action.endsWith('.update')) return 'bg-blue-100 text-blue-700'
  if (action === 'auth.login') return 'bg-gray-100 text-gray-600'
  return 'bg-gray-100 text-gray-600'
}

function isoLocal(dt: string): string {
  // datetime-local input value → ISO string with timezone
  return new Date(dt).toISOString()
}


function formatVal(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (v === '[redacted]') return '••••••••'
  return String(v)
}

function DiffPanel({ event }: { event: { old_value: Record<string, unknown> | null; new_value: Record<string, unknown> | null } }) {
  const old_ = event.old_value ?? {}
  const new_ = event.new_value ?? {}
  const keys = Array.from(new Set([...Object.keys(old_), ...Object.keys(new_)]))
  if (keys.length === 0) return <span className="text-xs text-gray-400 italic">no changes recorded</span>
  return (
    <div className="space-y-0.5">
      {keys.map(k => {
        const ov = old_[k], nv = new_[k]
        const changed = JSON.stringify(ov) !== JSON.stringify(nv)
        return (
          <div key={k} className="flex items-baseline gap-2 font-mono text-xs">
            <span className="text-gray-500 min-w-[140px] shrink-0">{k}</span>
            {changed ? (
              <>
                <span className="text-red-500 line-through">{formatVal(ov)}</span>
                <span className="text-gray-400">→</span>
                <span className="text-emerald-600 font-medium">{formatVal(nv)}</span>
              </>
            ) : (
              <span className="text-gray-400">{formatVal(nv)}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function AuditPage() {
  const [params, setParams] = useSearchParams()

  const actor = params.get('actor') ?? ''
  const action = params.get('action') ?? ''
  const resourceType = params.get('resource_type') ?? ''
  const fromTs = params.get('from_ts') ?? ''
  const toTs = params.get('to_ts') ?? ''
  const page = parseInt(params.get('page') ?? '1', 10)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  function set(key: string, value: string) {
    setParams(prev => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value); else next.delete(key)
      if (key !== 'page') next.delete('page')
      return next
    })
  }

  function clearAll() {
    setParams({})
  }

  function applyPreset(minutes: number) {
    // eslint-disable-next-line react-hooks/purity -- Date.now() is intentional here; this function is only called from a click handler, not during render
    const from = new Date(Date.now() - minutes * 60 * 1000).toISOString()
    setParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('from_ts', from)
      next.delete('to_ts')
      next.delete('page')
      return next
    })
  }

  const activeCount = useMemo(() =>
    [actor, action, resourceType, fromTs, toTs].filter(Boolean).length,
    [actor, action, resourceType, fromTs, toTs]
  )

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit', actor, action, resourceType, fromTs, toTs, page],
    queryFn: () => auditApi.list({
      actor: actor || undefined,
      action: action || undefined,
      resource_type: resourceType || undefined,
      from_ts: fromTs || undefined,
      to_ts: toTs || undefined,
      page,
      per_page: 50,
    }),
    staleTime: 15_000,
  })

  // Format datetime-local input value from ISO string
  function toDatetimeLocal(iso: string): string {
    if (!iso) return ''
    try {
      return new Date(iso).toISOString().slice(0, 16)
    } catch {
      return ''
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
        {activeCount > 0 && (
          <button
            onClick={clearAll}
            className="text-sm text-gray-500 hover:text-gray-700 underline"
          >
            Clear all filters
            <span className="ml-1.5 inline-flex items-center justify-center w-5 h-5 rounded-full bg-brand-600 text-white text-[10px] font-bold">
              {activeCount}
            </span>
          </button>
        )}
      </div>

      {/* Filter bar */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3 shadow-sm">
        <div className="flex flex-wrap gap-3 items-end">
          {/* Actor */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-500">Actor</label>
            <input
              type="search"
              placeholder="email or user ID"
              value={actor}
              onChange={(e) => set('actor', e.target.value)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-52"
            />
          </div>

          {/* Action */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-500">Action</label>
            <input
              type="search"
              placeholder="e.g. login, node.delete"
              value={action}
              onChange={(e) => set('action', e.target.value)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-44"
            />
          </div>

          {/* Resource type */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-500">Resource type</label>
            <select
              value={resourceType}
              onChange={(e) => set('resource_type', e.target.value)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option value="">All types</option>
              {RESOURCE_TYPES.map(rt => (
                <option key={rt} value={rt}>{rt}</option>
              ))}
            </select>
          </div>

          {data && (
            <span className="text-sm text-gray-500 ml-auto self-end pb-1.5">
              {data.total.toLocaleString()} events
            </span>
          )}
        </div>

        {/* Time range */}
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs font-medium text-gray-500 mr-1">Time range:</span>
          {PRESETS.map(p => (
            <button
              key={p.label}
              onClick={() => applyPreset(p.minutes)}
              className="px-2.5 py-1 text-xs rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-brand-400 hover:text-brand-600 transition-colors"
            >
              Last {p.label}
            </button>
          ))}
          <span className="text-xs text-gray-400 mx-1">or</span>
          <div className="flex items-center gap-2">
            <input
              type="datetime-local"
              value={toDatetimeLocal(fromTs)}
              onChange={(e) => set('from_ts', e.target.value ? isoLocal(e.target.value) : '')}
              className="px-2 py-1 text-xs border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <span className="text-xs text-gray-400">to</span>
            <input
              type="datetime-local"
              value={toDatetimeLocal(toTs)}
              onChange={(e) => set('to_ts', e.target.value ? isoLocal(e.target.value) : '')}
              className="px-2 py-1 text-xs border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
        </div>
      </div>

      {/* Table */}
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
                  <th className="px-4 py-3">Changes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                      No audit events match the current filters
                    </td>
                  </tr>
                )}
                {data?.items.map((e) => {
                  const hasChanges = (e.old_value && Object.keys(e.old_value).length > 0) || (e.new_value && Object.keys(e.new_value).length > 0)
                  const isExpanded = expandedId === e.id
                  return (
                    <>
                      <tr key={e.id} className={`hover:bg-gray-50 ${hasChanges ? 'cursor-pointer' : ''}`} onClick={() => hasChanges && setExpandedId(isExpanded ? null : e.id)}>
                        <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                          <span title={formatDistanceToNow(new Date(e.event_at), { addSuffix: true })}>
                            {formatLocalDateTime(e.event_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                          </span>
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
                        <td className="px-4 py-3 text-gray-400 text-xs">
                          {hasChanges ? (
                            <button className="text-brand-600 hover:underline text-xs" onClick={(ev) => { ev.stopPropagation(); setExpandedId(isExpanded ? null : e.id) }}>
                              {isExpanded ? '▾ hide' : '▸ diff'}
                            </button>
                          ) : '—'}
                        </td>
                      </tr>
                      {isExpanded && hasChanges && (
                        <tr key={`${e.id}-diff`} className="bg-gray-50">
                          <td colSpan={6} className="px-6 py-3 border-b border-gray-100">
                            <DiffPanel event={e} />
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
              </tbody>
            </table>
            {data && (
              <Pagination
                page={page}
                total={data.total}
                perPage={data.per_page}
                onPage={(p) => set('page', String(p))}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}
