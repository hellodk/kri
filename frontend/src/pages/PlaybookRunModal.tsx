import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { playbooksApi } from '../api/playbooks'
import type { PlaybookEntry } from '../api/playbooks'
import { fleetApi } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { useToastStore } from '../stores/toastStore'

const SYSTEM_VARS = new Set([
  'ansible_become', 'ansible_become_method', 'ansible_become_password',
  'ansible_ssh_common_args', 'ansible_ssh_pass', 'ansible_user',
])

interface Props {
  playbook: PlaybookEntry
  onClose: () => void
}

const STATUS_STYLE: Record<string, { label: string; colour: string }> = {
  pending:   { label: 'Queued',   colour: 'text-gray-500' },
  running:   { label: 'Running…', colour: 'text-brand-600' },
  completed: { label: 'Done ✓',   colour: 'text-emerald-700' },
  failed:    { label: 'Failed',   colour: 'text-red-700' },
}

function fmtDuration(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export function PlaybookRunModal({ playbook, onClose }: Props) {
  const [targetType, setTargetType] = useState<'node' | 'group'>('node')
  const [targetId, setTargetId] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [vars, setVars] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(playbook.default_vars).map(([k, v]) => [k, String(v ?? '')])
    )
  )
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  const { data: nodes } = useQuery({
    queryKey: ['nodes-for-playbook'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    enabled: targetType === 'node',
    staleTime: 60_000,
  })

  const { data: groups } = useQuery({
    queryKey: ['groups-for-playbook'],
    queryFn: () => groupsApi.list({ per_page: 200 }),
    enabled: targetType === 'group',
    staleTime: 60_000,
  })

  const { data: statsData } = useQuery({
    queryKey: ['playbook-stats', playbook.filename],
    queryFn: () => playbooksApi.getStats(playbook.filename),
    staleTime: 60_000,
  })

  const runMutation = useMutation({
    mutationFn: () => {
      const extravars: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(vars)) {
        if (v === 'true') extravars[k] = true
        else if (v === 'false') extravars[k] = false
        else if (v !== '' && !isNaN(Number(v))) extravars[k] = Number(v)
        else extravars[k] = v
      }
      return playbooksApi.run(playbook.filename, targetType, targetId, extravars)
    },
    onSuccess: (data) => { setJobId(data.job_id); toast('Playbook queued') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const { data: jobData } = useQuery({
    queryKey: ['ansible-job', jobId],
    queryFn: () => playbooksApi.getJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return (s === 'pending' || s === 'running') ? 3000 : false
    },
  })

  useEffect(() => {
    if (jobData?.status === 'completed' || jobData?.status === 'failed') {
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    }
  }, [jobData?.status, qc])

  const status = jobData?.status
  const { label, colour } = STATUS_STYLE[status ?? 'pending'] ?? STATUS_STYLE.pending
  const hasVars = Object.keys(vars).length > 0

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl flex flex-col max-h-[92vh]">

        {/* Fixed header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Run Playbook</h2>
            <div className="flex items-baseline gap-2">
              <p className="text-sm text-gray-500">{playbook.name}</p>
              {statsData && statsData.run_count > 0 && statsData.last_duration_seconds !== null && (
                <p className="text-sm text-gray-400">Last run: {fmtDuration(statsData.last_duration_seconds)}</p>
              )}
            </div>
          </div>
          <button onClick={onClose} className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-lg">×</button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
        {!jobId ? (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Target type</label>
              <div className="flex gap-4">
                {(['node', 'group'] as const).map((t) => (
                  <label key={t} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="radio" name="targetType" value={t}
                      checked={targetType === t}
                      onChange={() => { setTargetType(t); setTargetId('') }}
                      className="accent-brand-600" />
                    {t === 'node' ? 'Single node' : 'Group'}
                  </label>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {targetType === 'node' ? 'Node' : 'Group'}
              </label>
              <select required value={targetId} onChange={(e) => setTargetId(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600">
                <option value="">Select…</option>
                {targetType === 'node'
                  ? nodes?.items.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.hostname ?? n.minion_id} — {n.ip_address ?? 'no IP'}
                      </option>
                    ))
                  : groups?.items.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name} ({g.member_count} nodes)
                      </option>
                    ))
                }
              </select>
            </div>

            {hasVars && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Variables
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    (changes committed to git before run)
                  </span>
                </label>
                <div className="space-y-3 bg-gray-50 rounded-lg border border-gray-200 p-3 max-h-72 overflow-y-auto">
                  {Object.entries(vars).map(([key, value]) => {
                    const isSensitive = /password|secret|token|api_key|apikey|passphrase/i.test(key)
                    const isPlaceholder = value === key || /^changeme|^change.me|^<.*>$|^your.*/i.test(value)
                    const helpText = playbook.var_descriptions?.[key]
                    return (
                      <div key={key} className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono font-medium text-gray-800">{key}</span>
                          {isSensitive && (
                            <span className="text-xs text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">🔒 sensitive</span>
                          )}
                          {SYSTEM_VARS.has(key) && (
                            <span className="text-xs text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">⚠ system</span>
                          )}
                        </div>
                        {helpText && (
                          <p className="text-xs text-gray-500 leading-snug">{helpText}</p>
                        )}
                        <input
                          type={isSensitive ? 'password' : 'text'}
                          value={value}
                          placeholder={isSensitive ? `Enter value for ${key}…` : helpText ? `e.g. ${helpText.split('.')[0]}` : undefined}
                          onChange={(e) => setVars((prev) => ({ ...prev, [key]: e.target.value }))}
                          className={`w-full px-2.5 py-1.5 text-sm border rounded-lg focus:outline-none font-mono ${
                            isPlaceholder
                              ? 'border-red-300 bg-red-50 focus:border-red-500'
                              : SYSTEM_VARS.has(key)
                              ? 'border-amber-300 bg-amber-50 focus:border-amber-500'
                              : 'border-gray-300 focus:border-brand-600'
                          }`}
                        />
                        {isPlaceholder && (
                          <p className="text-xs text-red-600">⚠ Replace this placeholder with a real value before running</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            {/* SSH Credentials — resolved automatically, no prompt */}
            <div className="border-t border-gray-100 pt-4">
              <div className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5">
                <span className="text-base leading-none mt-0.5" aria-hidden>🔑</span>
                <p className="text-sm text-gray-600">
                  SSH credentials are resolved automatically for each host
                  <span className="text-gray-500"> (node&nbsp;→&nbsp;group&nbsp;→&nbsp;global settings)</span>.
                  The run output shows which source was used per host.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
              <div className={`text-sm font-semibold ${colour}`}>{label}</div>
              <div className="text-sm text-gray-600 flex-1">{jobData?.target_label}</div>
              {(status === 'pending' || status === 'running') && (
                <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
              )}
            </div>
            {(status === 'running' || status === 'pending') && (
              <p className="text-xs text-gray-400">
                Closing this window does not stop the playbook — it runs on the server until complete.
              </p>
            )}

            {jobData?.stdout && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Output</p>
                <pre className="text-sm font-mono bg-gray-900 text-gray-100 rounded-lg p-4 overflow-auto min-h-32 max-h-[40vh] whitespace-pre-wrap leading-relaxed">
                  {jobData.stdout}
                </pre>
              </div>
            )}

            {typeof jobData?.rc === 'number' && (
              <p className="text-xs text-gray-400">Exit code: {jobData.rc}</p>
            )}
          </div>
        )}
        </div>

        {/* Fixed footer */}
        <div className="px-6 py-4 border-t border-gray-200 shrink-0">
        {!jobId ? (
          <form onSubmit={(e) => { e.preventDefault(); runMutation.mutate() }}>
            <div className="flex gap-3">
              <button type="button" onClick={onClose}
                className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button type="submit" disabled={!targetId || runMutation.isPending}
                className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                {runMutation.isPending ? 'Starting…' : 'Run Playbook'}
              </button>
            </div>
          </form>
        ) : (
          <button onClick={onClose}
            className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            {status === 'completed' || status === 'failed' ? 'Close' : 'Close — runs in background (see Executions tab)'}
          </button>
        )}
        </div>

      </div>
    </div>
  )
}
