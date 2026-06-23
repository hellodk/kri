import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { executionsApi } from '../api/executions'
import { playbooksApi, type AnsibleJob } from '../api/playbooks'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow, formatDuration, intervalToDuration } from 'date-fns'
import { formatIST } from '../utils/time'
import { useFilterStore } from '../stores/filterStore'

function jobDuration(job: { started_at: string | null; completed_at: string | null }): string {
  if (!job.started_at || !job.completed_at) return '—'
  const duration = intervalToDuration({ start: new Date(job.started_at), end: new Date(job.completed_at) })
  return formatDuration(duration, { format: ['minutes', 'seconds'] }) || '<1s'
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === 'completed'  ? 'bg-green-100 text-green-800' :
    status === 'failed'     ? 'bg-red-100 text-red-800' :
    status === 'running'    ? 'bg-blue-100 text-blue-800 animate-pulse' :
    status === 'cancelled'  ? 'bg-amber-100 text-amber-800' :
    'bg-gray-100 text-gray-700'
  return <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls}`}>{status}</span>
}

export function ExecutionHistory() {
  const [page, setPage] = useState(1)
  const [ansiblePage, setAnsiblePage] = useState(1)
  const { executionStatus } = useFilterStore()
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const statusFilter = searchParams.get('status') || 'all'
  const typeFilter = searchParams.get('type') || 'all'
  const dateFrom = searchParams.get('from') || ''
  const dateTo = searchParams.get('to') || ''

  // Salt execution history (ExecutionJob — from minion ingest)
  const { data: saltData, isLoading: saltLoading, isError: saltError, refetch: saltRefetch } = useQuery({
    queryKey: ['executions', executionStatus, page],
    queryFn: () => executionsApi.list({ status: executionStatus || undefined, page, per_page: 25 }),
    staleTime: 10_000,
    refetchInterval: 15_000,
    enabled: typeFilter === 'all' || typeFilter === 'salt',
  })

  // Ansible playbook runs (AnsibleJob — from local ansible-runner)
  const { data: ansibleData, isLoading: ansibleLoading, isError: ansibleError, refetch: ansibleRefetch } = useQuery({
    queryKey: ['ansible-jobs', executionStatus, ansiblePage],
    queryFn: () => playbooksApi.listJobs({ status: executionStatus || undefined, page: ansiblePage, per_page: 25 }),
    staleTime: 10_000,
    refetchInterval: (q) => {
      const hasRunning = (q.state.data ?? []).some((j: AnsibleJob) => j.status === 'running' || j.status === 'pending')
      return hasRunning ? 3000 : 15_000
    },
    enabled: typeFilter === 'all' || typeFilter === 'playbook',
  })

  const saltItems = (saltData?.items ?? []).filter((r) => {
    const statusMatch = statusFilter === 'all' || r.status === statusFilter
    const typeMatch = typeFilter === 'all' || typeFilter === 'salt' || (r.type ?? '').toLowerCase().includes(typeFilter.toLowerCase())
    const fromMatch = !dateFrom || (r.started_at && r.started_at >= dateFrom)
    const toMatch = !dateTo || (r.started_at && r.started_at <= dateTo + 'T23:59:59')
    return statusMatch && typeMatch && fromMatch && toMatch
  })

  const ansibleItems = (ansibleData ?? []).filter((j: AnsibleJob) => {
    const statusMatch = statusFilter === 'all' || j.status === statusFilter
    const fromMatch = !dateFrom || (j.started_at && j.started_at >= dateFrom)
    const toMatch = !dateTo || (j.started_at && j.started_at <= dateTo + 'T23:59:59')
    return statusMatch && fromMatch && toMatch
  })

  const isLoading = saltLoading || ansibleLoading
  const isError = saltError && ansibleError

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Execution History</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => { setSearchParams((p) => { p.set('status', e.target.value); return p }); setPage(1); setAnsiblePage(1) }}
          className="text-sm border border-gray-200 rounded-md px-3 py-1.5 bg-white text-gray-900"
        >
          <option value="all">All Statuses</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
          <option value="pending">Pending</option>
        </select>
        <select
          value={typeFilter}
          onChange={(e) => { setSearchParams((p) => { p.set('type', e.target.value); return p }); setPage(1); setAnsiblePage(1) }}
          className="text-sm border border-gray-200 rounded-md px-3 py-1.5 bg-white text-gray-900"
        >
          <option value="all">All Types</option>
          <option value="playbook">Ansible Playbook</option>
          <option value="salt">Salt State</option>
        </select>
        <input type="date" value={dateFrom}
          onChange={(e) => { setSearchParams((p) => { p.set('from', e.target.value); return p }); setPage(1) }}
          className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white text-gray-900"
        />
        <span className="text-sm text-gray-500 self-center">–</span>
        <input type="date" value={dateTo}
          onChange={(e) => { setSearchParams((p) => { p.set('to', e.target.value); return p }); setPage(1) }}
          className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white text-gray-900"
        />
        {(statusFilter !== 'all' || typeFilter !== 'all' || dateFrom || dateTo) && (
          <button onClick={() => { setSearchParams({}); setPage(1); setAnsiblePage(1) }}
            className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-md px-3 py-1.5 hover:bg-gray-50"
          >✕ Clear</button>
        )}
      </div>

      {isLoading && <Skeleton rows={8} />}
      {isError && <ErrorState message="Failed to load executions" retry={() => { saltRefetch(); ansibleRefetch() }} />}

      {/* Ansible Playbook Runs */}
      {(typeFilter === 'all' || typeFilter === 'playbook') && !ansibleLoading && (
        <div className="bg-white rounded-lg shadow-xs border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">▷ Ansible Playbook Runs</h2>
            <span className="text-xs text-gray-400">{ansibleItems.length} run{ansibleItems.length !== 1 ? 's' : ''}</span>
          </div>
          {ansibleError ? (
            <div className="px-4 py-3 text-sm text-red-600">Failed to load playbook runs</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Playbook</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Target</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Duration</th>
                  <th className="px-4 py-3">RC</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {ansibleItems.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center text-2xl">▷</div>
                        <div>
                          <p className="text-sm font-medium text-gray-700">No playbook runs yet</p>
                          <p className="text-xs text-gray-400 mt-1">Go to Automation → Playbooks to run your first playbook</p>
                        </div>
                        <a
                          href="/automation?tab=playbooks"
                          className="px-4 py-1.5 text-xs font-medium bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors"
                        >
                          Browse Playbooks →
                        </a>
                      </div>
                    </td>
                  </tr>
                )}
                {ansibleItems.map((j: AnsibleJob) => (
                  <tr key={j.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link to={`/playbook-job/${j.id}`}
                        className="text-brand-600 hover:underline font-mono text-xs">
                        {j.playbook}
                      </Link>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={j.status} /></td>
                    <td className="px-4 py-3 text-gray-600 text-xs">
                      <span className="inline-flex items-center gap-1">
                        <span className="text-gray-400 text-xs">{j.target_type === 'node' ? '💻' : '▦'}</span>
                        <span>{j.target_label || j.target_type}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      <span title={j.started_at ? formatIST(j.started_at) : undefined}>
                        {j.started_at ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true }) : '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{jobDuration(j)}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs font-mono">
                      {typeof j.rc === 'number' ? (
                        <span className={j.rc === 0 ? 'text-green-600' : 'text-red-600'}>{j.rc}</span>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-2">
                      {(j.status === 'running' || j.status === 'pending') && (
                        <button
                          onClick={async (e) => {
                            e.stopPropagation()
                            if (window.confirm(`Cancel "${j.playbook}"?`)) {
                              try {
                                await playbooksApi.cancel(j.id)
                                qc.invalidateQueries({ queryKey: ['ansible-jobs'] })
                              } catch { /* ignore */ }
                            }
                          }}
                          className="text-xs text-red-500 hover:text-red-700 hover:bg-red-50 px-2 py-0.5 rounded border border-red-200 transition-colors"
                          title="Cancel this job"
                        >
                          ✕ Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Salt State Runs */}
      {(typeFilter === 'all' || typeFilter === 'salt') && !saltLoading && (
        <div className="bg-white rounded-lg shadow-xs border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">⬡ Salt State Runs</h2>
            <span className="text-xs text-gray-400">{saltItems.length} / {saltData?.total ?? 0} jobs</span>
          </div>
          {saltError ? (
            <div className="px-4 py-3 text-sm text-red-600">Failed to load salt executions</div>
          ) : (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Target</th>
                    <th className="px-4 py-3">Triggered By</th>
                    <th className="px-4 py-3">Started</th>
                    <th className="px-4 py-3">Duration</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {saltItems.length === 0 && !saltLoading && (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center">
                        <div className="flex flex-col items-center gap-3">
                          <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center text-2xl">⬡</div>
                          <div>
                            <p className="text-sm font-medium text-gray-700">No Salt state runs yet</p>
                            <p className="text-xs text-gray-400 mt-1">Apply a state from Automation → Salt Ops</p>
                          </div>
                          <a
                            href="/automation?tab=salt-ops"
                            className="px-4 py-1.5 text-xs font-medium bg-gray-700 text-white rounded-lg hover:bg-gray-800 transition-colors"
                          >
                            Go to Salt Ops →
                          </a>
                        </div>
                      </td>
                    </tr>
                  )}
                  {saltItems.map((j) => (
                    <tr key={j.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <Link to={`/executions/${j.id}`} className="text-brand-600 hover:underline font-mono text-xs">{j.type}</Link>
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={j.status} /></td>
                      <td className="px-4 py-3 text-gray-600 text-xs">
                        <span className="inline-flex items-center gap-1">
                          <span className="text-gray-400">{j.target_type === 'node' ? '💻' : '▦'}</span>
                          <span>{j.target_label || j.target_type}</span>
                          {j.target_id && !j.target_label && (
                            <span className="text-gray-400 font-mono">{j.target_id.slice(0, 8)}</span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">{j.triggered_by}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">
                        <span title={j.started_at ? formatIST(j.started_at) : undefined}>
                          {j.started_at ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true }) : '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{jobDuration(j)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {saltData && <Pagination page={page} total={saltData.total} perPage={saltData.per_page} onPage={setPage} />}
            </>
          )}
        </div>
      )}
    </div>
  )
}
