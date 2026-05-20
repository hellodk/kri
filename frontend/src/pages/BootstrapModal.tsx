import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'

type LogTab = 'pillar' | 'ansible'

interface Props {
  onClose: () => void
}

type Mode = 'single' | 'bulk'

interface BulkJob {
  minionId: string
  targetIp: string
  extraTags: Record<string, string>
  nodeId: string | null
  error: string | null
}

const STATUS_LABEL: Record<string, { label: string; colour: string }> = {
  pending:      { label: 'Queued',   colour: 'text-gray-500' },
  bootstrapping:{ label: 'Running…', colour: 'text-brand-600' },
  completed:    { label: 'Done ✓',   colour: 'text-emerald-700' },
  failed:       { label: 'Failed',   colour: 'text-red-700' },
}

// ─── Single bootstrap ────────────────────────────────────────────────────────

function SingleMode({ onClose }: { onClose: () => void }) {
  const [minionId, setMinionId] = useState('')
  const [targetIp, setTargetIp] = useState('')
  const [nodeId, setNodeId] = useState<string | null>(null)
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  const bootstrapMutation = useMutation({
    mutationFn: () => ansibleApi.bootstrap(minionId, targetIp),
    onSuccess: (data) => { setNodeId(data.node_id); toast('Bootstrap started') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const { data: statusData } = useQuery({
    queryKey: ['bootstrap-status', nodeId],
    queryFn: () => ansibleApi.bootstrapStatus(nodeId!),
    enabled: !!nodeId,
    refetchInterval: (query) => {
      const s = query.state.data?.bootstrap_status
      return (s === 'pending' || s === 'bootstrapping') ? 3000 : false
    },
  })

  useEffect(() => {
    if (statusData?.bootstrap_status === 'completed') {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    }
  }, [statusData?.bootstrap_status, qc])

  const status = statusData?.bootstrap_status
  const { label, colour } = STATUS_LABEL[status ?? 'pending'] ?? STATUS_LABEL.pending

  const [showLogs, setShowLogs] = useState(false)
  const [logTab, setLogTab] = useState<LogTab>('ansible')

  const { data: logsData, refetch: refetchLogs } = useQuery({
    queryKey: ['bootstrap-logs', nodeId],
    queryFn: () => ansibleApi.bootstrapLogs(nodeId!),
    enabled: false,
  })

  if (!nodeId) {
    return (
      <form onSubmit={(e) => { e.preventDefault(); bootstrapMutation.mutate() }} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Minion ID <span className="text-gray-400 font-normal">(e.g. mac-mini-01)</span>
          </label>
          <input required value={minionId} onChange={(e) => setMinionId(e.target.value)}
            placeholder="mac-mini-01"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">IP address</label>
          <input required value={targetIp} onChange={(e) => setTargetIp(e.target.value)}
            placeholder="10.0.1.11"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
        </div>
        <p className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-lg p-3">
          Make sure Remote Login (SSH) is enabled before bootstrapping.
        </p>
        <div className="flex gap-3 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Cancel
          </button>
          <button type="submit" disabled={bootstrapMutation.isPending}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
            {bootstrapMutation.isPending ? 'Starting…' : 'Bootstrap'}
          </button>
        </div>
      </form>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
        <div className={`text-sm font-semibold ${colour}`}>{label}</div>
        <div className="text-sm text-gray-600 flex-1">{minionId} @ {targetIp}</div>
        {(status === 'pending' || status === 'bootstrapping') && (
          <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
        )}
      </div>
      {statusData?.bootstrap_error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-mono">
          {statusData.bootstrap_error}
        </div>
      )}
      {status === 'completed' && (
        <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
          Bootstrap complete. Node will appear in the fleet once Salt minion connects.
        </p>
      )}

      {/* Log viewer */}
      {nodeId && (
        <button
          onClick={() => { setShowLogs(!showLogs); if (!showLogs) refetchLogs() }}
          className="w-full py-2 border border-gray-200 text-gray-600 rounded-lg text-xs font-medium hover:bg-gray-50 flex items-center justify-center gap-1"
        >
          {showLogs ? '▲ Hide logs' : '▼ View logs (Salt pillar + Ansible output)'}
        </button>
      )}

      {showLogs && logsData && (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          {/* Tabs */}
          <div className="flex border-b border-gray-200 bg-gray-50">
            {(['ansible', 'pillar'] as LogTab[]).map((t) => (
              <button key={t} onClick={() => setLogTab(t)}
                className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
                  logTab === t
                    ? 'border-brand-600 text-brand-700 bg-white'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}>
                {t === 'ansible' ? 'Ansible output' : `Salt pillar (${logsData.pillar_path?.split('/').pop()})`}
              </button>
            ))}
          </div>
          {/* Content */}
          <pre className="text-xs font-mono bg-gray-900 text-gray-100 p-3 overflow-auto max-h-72 whitespace-pre-wrap">
            {logTab === 'ansible'
              ? (logsData.ansible_stdout || '(no output captured yet — run in progress or not started)')
              : (logsData.pillar || '(pillar file not found)')}
          </pre>
        </div>
      )}

      <button onClick={onClose}
        className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
        {status === 'completed' || status === 'failed' ? 'Close' : 'Close (runs in background)'}
      </button>
    </div>
  )
}

// ─── Bulk job status row ──────────────────────────────────────────────────────

function BulkJobRow({ job }: { job: BulkJob }) {
  const { data } = useQuery({
    queryKey: ['bootstrap-status', job.nodeId],
    queryFn: () => ansibleApi.bootstrapStatus(job.nodeId!),
    enabled: !!job.nodeId,
    refetchInterval: (query) => {
      const s = query.state.data?.bootstrap_status
      return (s === 'pending' || s === 'bootstrapping') ? 3000 : false
    },
  })

  const status = job.error ? 'failed' : (data?.bootstrap_status ?? (job.nodeId ? 'pending' : 'queuing'))
  const { label, colour } = STATUS_LABEL[status] ?? { label: status, colour: 'text-gray-500' }

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="py-2 pr-3">
        <span className="font-mono text-xs text-gray-800">{job.minionId}</span>
        {Object.keys(job.extraTags).length > 0 && (
          <div className="flex flex-wrap gap-1 mt-0.5">
            {Object.entries(job.extraTags).map(([k, v]) => (
              <span key={k} className="text-xs bg-brand-50 text-brand-700 border border-brand-100 px-1 rounded">
                {k}={v}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-gray-500">{job.targetIp}</td>
      <td className="py-2">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${colour}`}>{label}</span>
          {(status === 'pending' || status === 'bootstrapping') && (
            <div className="w-3 h-3 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
          )}
        </div>
        {(job.error || data?.bootstrap_error) && (
          <p className="text-xs text-red-600 mt-0.5 font-mono truncate max-w-xs">
            {job.error ?? data?.bootstrap_error}
          </p>
        )}
      </td>
    </tr>
  )
}

// ─── Bulk bootstrap ───────────────────────────────────────────────────────────

function BulkMode({ onClose }: { onClose: () => void }) {
  const [input, setInput] = useState('')
  const [jobs, setJobs] = useState<BulkJob[]>([])
  const [launching, setLaunching] = useState(false)
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  const parsedRows = input
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))
    .map((l) => {
      // Format: minion-id  IP  [key=value ...]
      // Extra columns (serial=XXX location=rack1 role=worker etc.) stored as tags
      const parts = l.split(/[\s,]+/)
      const minionId = parts[0] ?? ''
      const targetIp = parts[1] ?? ''
      const extraTags: Record<string, string> = {}
      parts.slice(2).forEach((p) => {
        const idx = p.indexOf('=')
        if (idx > 0) extraTags[p.slice(0, idx)] = p.slice(idx + 1)
      })
      return { minionId, targetIp, extraTags }
    })
    .filter((r) => r.minionId && r.targetIp)

  const allDone = jobs.length > 0 && jobs.every((j) => j.nodeId !== null || j.error !== null)

  async function launch() {
    if (parsedRows.length === 0) return
    setLaunching(true)
    const initial: BulkJob[] = parsedRows.map((r) => ({ ...r, extraTags: r.extraTags, nodeId: null, error: null }))
    setJobs(initial)

    // Fire all requests in parallel
    const results = await Promise.allSettled(
      parsedRows.map((r) => ansibleApi.bootstrap(r.minionId, r.targetIp))
    )

    setJobs(parsedRows.map((r, i) => {
      const res = results[i]
      return {
        ...r,
        nodeId: res.status === 'fulfilled' ? res.value.node_id : null,
        error: res.status === 'rejected' ? String(res.reason) : null,
      }
    }))
    setLaunching(false)
    toast(`Launched ${parsedRows.length} bootstrap job(s)`)
    qc.invalidateQueries({ queryKey: ['fleet-overview'] })
  }

  if (jobs.length === 0) {
    return (
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            One host per line —{' '}
            <code className="text-xs bg-gray-100 px-1 rounded">minion-id  IP  [key=value …]</code>
          </label>
          <textarea
            rows={8}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`# minion-id  IP  [optional key=value pairs]\nmac-mini-01  10.0.1.11  serial=C02XK1JFLVCG  location=rack-A  role=worker\nmac-mini-02  10.0.1.12  serial=C02XK1JFLVCH  location=rack-A\nmac-mini-03  10.0.1.13`}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 font-mono resize-none"
          />
          {parsedRows.length > 0 && (
            <p className="text-xs text-gray-500 mt-1">
              {parsedRows.length} host{parsedRows.length !== 1 ? 's' : ''} detected
              {parsedRows.some((r) => Object.keys(r.extraTags).length > 0) &&
                ' · extra tags will be applied after bootstrap'}
            </p>
          )}
        </div>
        <p className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-lg p-3">
          All jobs launch in parallel. Remote Login (SSH) must be enabled on each Mac Mini.
          Credentials are taken from Settings.
        </p>
        <div className="flex gap-3">
          <button type="button" onClick={onClose}
            className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Cancel
          </button>
          <button
            disabled={parsedRows.length === 0 || launching}
            onClick={launch}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
            {launching ? 'Launching…' : `Bootstrap ${parsedRows.length || ''} nodes`}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="bg-gray-50 rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="px-3 py-2 text-left">Minion ID</th>
              <th className="px-3 py-2 text-left">IP</th>
              <th className="px-3 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody className="px-3">
            {jobs.map((job) => (
              <BulkJobRow key={job.minionId} job={job} />
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={onClose}
        className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
        {allDone ? 'Close' : 'Close (jobs run in background)'}
      </button>
    </div>
  )
}

// ─── Modal shell ──────────────────────────────────────────────────────────────

export function BootstrapModal({ onClose }: Props) {
  const [mode, setMode] = useState<Mode>('single')

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-gray-900">Bootstrap Mac Mini</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {/* Mode tabs */}
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mb-5">
          {(['single', 'bulk'] as Mode[]).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                mode === m ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}>
              {m === 'single' ? 'Single node' : 'Bulk (multiple nodes)'}
            </button>
          ))}
        </div>

        {mode === 'single' ? <SingleMode onClose={onClose} /> : <BulkMode onClose={onClose} />}
      </div>
    </div>
  )
}
