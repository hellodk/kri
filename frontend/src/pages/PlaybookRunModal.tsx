import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { playbooksApi } from '../api/playbooks'
import type { PlaybookEntry } from '../api/playbooks'
import { fleetApi } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { useToastStore } from '../stores/toastStore'
import { LogPane } from '../lib/LogPane'

// Running job output panel — fills available height, auto-scrolls while live
function JobOutput({ jobData, jobId, status, label, colour }: {
  jobData: { target_label?: string; stdout?: string | null; rc?: number | null } | undefined
  jobId: string | null
  status: string | undefined
  label: string
  colour: string
}) {
  const isLive = status === 'pending' || status === 'running'

  return (
    <div className="flex flex-col h-full space-y-3">
      {/* Status bar */}
      <div className="flex items-center gap-3 px-4 py-3 bg-gray-50 rounded-xl border border-gray-200 shrink-0">
        <span className={`text-sm font-semibold ${colour}`}>{label}</span>
        {jobData?.target_label && (
          <span className="text-sm text-gray-600 flex-1">on <span className="font-medium font-mono">{jobData.target_label}</span></span>
        )}
        {isLive && (
          <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin shrink-0" />
        )}
        {jobId && (
          <Link
            to={`/playbook-job/${jobId}`}
            className="text-xs text-brand-600 hover:underline shrink-0"
            onClick={() => {/* modal stays open; user navigates in same tab */}}
          >
            Full logs →
          </Link>
        )}
      </div>

      {/* Background notice */}
      {isLive && (
        <div className="flex items-center gap-2 px-3 py-2 bg-blue-50 border border-blue-100 rounded-lg shrink-0">
          <span className="text-blue-400 text-xs">ℹ</span>
          <p className="text-xs text-blue-700">Closing this window does not stop the playbook — it continues running on the server.</p>
        </div>
      )}

      {/* Log output — fills available space (shared LogPane handles tail-follow) */}
      <div className="flex-1 flex flex-col min-h-0">
        <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1 shrink-0">Output</p>
        <LogPane raw={jobData?.stdout || ''} isLive={isLive} emptyText="No output recorded." className="rounded-lg" />
      </div>

      {/* Exit code */}
      {typeof jobData?.rc === 'number' && (
        <p className="text-xs text-gray-400 shrink-0">
          Exit code: <span className={jobData.rc === 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>{jobData.rc}</span>
        </p>
      )}
    </div>
  )
}

// Eye-icon show/hide input — same pattern as LoginPage for consistency
function SensitiveInput({ value, onChange, placeholder, isSystemVar }: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  isSystemVar?: boolean
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full px-2.5 py-1.5 pr-9 text-sm border rounded-lg focus:outline-none font-mono ${
          isSystemVar
            ? 'border-amber-300 bg-amber-50 focus:border-amber-500'
            : 'border-gray-300 focus:border-brand-600'
        }`}
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors p-0.5"
        aria-label={show ? 'Hide' : 'Show'}
      >
        {show ? (
          <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
        )}
      </button>
    </div>
  )
}

const SYSTEM_VARS = new Set([
  'ansible_become', 'ansible_become_method', 'ansible_become_password',
  'ansible_ssh_common_args', 'ansible_ssh_pass', 'ansible_user',
])

interface Props {
  playbook: PlaybookEntry
  onClose: () => void
  // Optional pre-fill for re-run
  initialTargetType?: 'node' | 'group'
  initialTargetId?: string
  initialVars?: Record<string, string>
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

export function PlaybookRunModal({ playbook, onClose, initialTargetType, initialTargetId, initialVars }: Props) {
  const [targetType, setTargetType] = useState<'node' | 'group'>(initialTargetType ?? 'node')
  const [targetId, setTargetId] = useState(initialTargetId ?? '')
  const [verbosity, setVerbosity] = useState(0)
  const [jobId] = useState<string | null>(null)
  const [vars, setVars] = useState<Record<string, string>>(
    initialVars ?? Object.fromEntries(
      Object.entries(playbook.default_vars).map(([k, v]) => [k, String(v ?? '')])
    )
  )
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()
  const navigate = useNavigate()

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
      return playbooksApi.run(playbook.filename, targetType, targetId, extravars, undefined, undefined, verbosity)
    },
    onSuccess: (data) => {
      toast('Playbook queued')
      onClose()
      navigate(`/playbook-job/${data.job_id}`)
    },
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
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl flex flex-col max-h-[92vh]">

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

        {/* Body — scrollable for pre-run form, flex for running output */}
        <div className={`flex-1 px-6 py-5 min-h-0 ${jobId ? 'flex flex-col overflow-hidden' : 'overflow-y-auto'}`}>
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
                        {isSensitive ? (
                          <SensitiveInput
                            value={value}
                            onChange={(v) => setVars((prev) => ({ ...prev, [key]: v }))}
                            placeholder={`Enter ${key}…`}
                            isSystemVar={SYSTEM_VARS.has(key)}
                          />
                        ) : (
                          <input
                            type="text"
                            value={value}
                            onChange={(e) => setVars((prev) => ({ ...prev, [key]: e.target.value }))}
                            className={`w-full px-2.5 py-1.5 text-sm border rounded-lg focus:outline-none font-mono ${
                              SYSTEM_VARS.has(key)
                                ? 'border-amber-300 bg-amber-50 focus:border-amber-500'
                                : 'border-gray-300 focus:border-brand-600'
                            }`}
                          />
                        )}
                        {isPlaceholder && (
                          <p className="text-xs text-amber-600">⚠ Replace this placeholder with a real value before running</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            {/* Verbosity */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Verbosity</label>
              <div className="flex gap-2">
                {[
                  { value: 0, label: 'Default' },
                  { value: 1, label: '-v' },
                  { value: 2, label: '-vv' },
                  { value: 3, label: '-vvv' },
                  { value: 4, label: '-vvvv' },
                ].map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setVerbosity(value)}
                    className={`px-3 py-1 text-xs rounded-lg border font-mono transition-colors ${
                      verbosity === value
                        ? 'bg-brand-600 text-white border-brand-600'
                        : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {verbosity > 0 && (
                <p className="text-xs text-gray-400 mt-1">Higher verbosity shows more Ansible detail in the output log.</p>
              )}
            </div>

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
          <JobOutput jobData={jobData} jobId={jobId} status={status} label={label} colour={colour} />
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
          <div className="flex justify-end">
            <button onClick={onClose}
              className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
              {status === 'completed' || status === 'failed' ? 'Close' : 'Close'}
            </button>
          </div>
        )}
        </div>

      </div>
    </div>
  )
}
