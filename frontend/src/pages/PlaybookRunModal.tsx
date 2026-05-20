import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { playbooksApi } from '../api/playbooks'
import type { PlaybookEntry } from '../api/playbooks'
import { fleetApi } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { useToastStore } from '../stores/toastStore'

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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-lg mx-4 flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Run Playbook</h2>
            <p className="text-sm text-gray-500">{playbook.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {!jobId ? (
          <form onSubmit={(e) => { e.preventDefault(); runMutation.mutate() }} className="space-y-5">
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
                <div className="space-y-2 bg-gray-50 rounded-lg border border-gray-200 p-3">
                  {Object.entries(vars).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-xs font-mono text-gray-600 w-40 shrink-0">{key}</span>
                      <input
                        type="text"
                        value={value}
                        onChange={(e) => setVars((prev) => ({ ...prev, [key]: e.target.value }))}
                        className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:border-brand-600 font-mono"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-3 pt-1">
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
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
              <div className={`text-sm font-semibold ${colour}`}>{label}</div>
              <div className="text-sm text-gray-600 flex-1">{jobData?.target_label}</div>
              {(status === 'pending' || status === 'running') && (
                <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
              )}
            </div>

            {jobData?.stdout && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Output</p>
                <pre className="text-xs font-mono bg-gray-900 text-gray-100 rounded-lg p-3 overflow-x-auto max-h-64 whitespace-pre-wrap">
                  {jobData.stdout}
                </pre>
              </div>
            )}

            {typeof jobData?.rc === 'number' && (
              <p className="text-xs text-gray-400">Exit code: {jobData.rc}</p>
            )}

            <button onClick={onClose}
              className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
              {status === 'completed' || status === 'failed' ? 'Close' : 'Close (runs in background)'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
