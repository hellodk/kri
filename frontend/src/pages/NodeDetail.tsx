import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { driftApi } from '../api/drift'
import { sbomApi } from '../api/sbom'
import { executionsApi } from '../api/executions'
import { ansibleApi, type BootstrapRunSummary } from '../api/ansible'
import { nodeSecretsApi } from '../api/nodeSecrets'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { WebSSHTerminal } from '../components/WebSSHTerminal'
import { VNCViewer } from '../components/VNCViewer'
import { formatDistanceToNow, format } from 'date-fns'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useToastStore } from '../stores/toastStore'
import { api } from '../api/client'

const BOOTSTRAP_STATUS_STYLE: Record<string, { label: string; colour: string; bg: string }> = {
  unregistered: { label: 'Not bootstrapped', colour: 'text-gray-500', bg: 'bg-gray-50 border-gray-200' },
  pending:      { label: 'Queued',           colour: 'text-gray-600', bg: 'bg-gray-50 border-gray-200' },
  bootstrapping:{ label: 'Running…',         colour: 'text-brand-600', bg: 'bg-brand-50 border-brand-200' },
  completed:    { label: 'Completed',        colour: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  failed:       { label: 'Failed',           colour: 'text-red-700', bg: 'bg-red-50 border-red-200' },
}

type Tab = 'overview' | 'drift' | 'sbom' | 'executions' | 'bootstrap-history' | 'secrets'

export function NodeDetail() {
  const { nodeId } = useParams<{ nodeId: string }>()
  const [tab, setTab] = useState<Tab>('overview')
  const [execPage, setExecPage] = useState(1)
  const [compPage, setCompPage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [tagKey, setTagKey] = useState('')
  const [tagValue, setTagValue] = useState('')
  const [collectingGrains, setCollectingGrains] = useState(false)
  const [grainTaskId, setGrainTaskId] = useState<string | null>(null)
  const [showRebootstrap, setShowRebootstrap] = useState(false)
  const [rebootstrapIp, setRebootstrapIp] = useState('')
  const [rebootstrapping, setRebootstrapping] = useState(false)
  const [showSSH, setShowSSH] = useState(false)
  const [showVNC, setShowVNC] = useState(false)
  const [sbomFilter, setSbomFilter] = useState('')
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null)
  const [triggeringScan, setTriggeringScan] = useState(false)
  // Secrets tab state
  const [secretKey, setSecretKey] = useState('')
  const [secretValue, setSecretValue] = useState('')
  const [secretDesc, setSecretDesc] = useState('')
  const [secretShowValue, setSecretShowValue] = useState(false)
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const { data: node, isLoading, isError, refetch } = useQuery({
    queryKey: ['node', nodeId],
    queryFn: () => fleetApi.node(nodeId!),
    staleTime: 60_000,
    enabled: !!nodeId,
  })

  const { data: latestDrift } = useQuery({
    queryKey: ['drift-latest', nodeId],
    queryFn: () => driftApi.latest(nodeId!),
    staleTime: 60_000,
    enabled: !!nodeId && tab === 'drift',
  })

  const { data: driftHistory } = useQuery({
    queryKey: ['drift-history', nodeId],
    queryFn: () => driftApi.history(nodeId!, { per_page: 30 }),
    staleTime: 60_000,
    enabled: !!nodeId && tab === 'drift',
  })

  const { data: sbomScanHistory } = useQuery({
    queryKey: ['sbom-scans', nodeId],
    queryFn: () => sbomApi.scans(nodeId!, { per_page: 50 }),
    staleTime: 300_000,
    enabled: !!nodeId && tab === 'sbom',
  })

  const activeScanId = selectedScanId ?? sbomScanHistory?.items[0]?.id
  const activeScan = sbomScanHistory?.items.find((s) => s.id === activeScanId) ?? sbomScanHistory?.items[0]

  const { data: components } = useQuery({
    queryKey: ['sbom-components', nodeId, activeScanId, compPage],
    queryFn: () => sbomApi.components(nodeId!, activeScanId!, { page: compPage, per_page: 200 }),
    staleTime: 300_000,
    enabled: !!activeScanId,
  })

  const { data: nodeVulns } = useQuery({
    queryKey: ['node-vulns', nodeId],
    queryFn: () => api.get<{ vulnerabilities: Array<{ package_name: string; severity: string; cve_id: string }> }>(`/api/v1/security/nodes/${nodeId}`),
    staleTime: 300_000,
    enabled: !!nodeId && tab === 'sbom',
  })

  const vulnsByPkg = (nodeVulns?.vulnerabilities ?? []).reduce<Record<string, string[]>>((acc, v) => {
    if (!acc[v.package_name]) acc[v.package_name] = []
    acc[v.package_name].push(v.severity)
    return acc
  }, {})

  const { data: grainTaskStatus } = useQuery({
    queryKey: ['grain-task', grainTaskId],
    queryFn: () => api.get<{ task_id: string; state: string; result?: unknown }>(`/api/v1/ansible/tasks/${grainTaskId}`),
    enabled: !!grainTaskId,
    refetchInterval: (q) => {
      const state = q.state.data?.state
      return state === 'PENDING' || state === 'STARTED' ? 2000 : false
    },
  })

  const { data: executions } = useQuery({
    queryKey: ['executions-node', nodeId, execPage],
    queryFn: () => executionsApi.list({ node_id: nodeId!, page: execPage, per_page: 25 }),
    staleTime: 10_000,
    enabled: !!nodeId && tab === 'executions',
  })

  const { data: bootstrapHistory } = useQuery({
    queryKey: ['bootstrap-history', nodeId, historyPage],
    queryFn: () => ansibleApi.bootstrapHistory(nodeId!, historyPage),
    staleTime: 15_000,
    enabled: !!nodeId && tab === 'bootstrap-history',
  })

  const { data: expandedRun } = useQuery({
    queryKey: ['bootstrap-run-detail', nodeId, expandedRunId],
    queryFn: () => ansibleApi.bootstrapRunDetail(nodeId!, expandedRunId!),
    staleTime: 60_000,
    enabled: !!nodeId && !!expandedRunId,
  })

  const { data: platformSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
    staleTime: 60_000,
  })
  const vncEnabled = platformSettings?.vnc_enabled ?? false

  const { data: nodeSecrets } = useQuery({
    queryKey: ['node-secrets', nodeId],
    queryFn: () => nodeSecretsApi.list(nodeId!),
    staleTime: 30_000,
    enabled: !!nodeId && tab === 'secrets',
  })

  const addSecretMutation = useMutation({
    mutationFn: () =>
      nodeSecretsApi.upsert(nodeId!, secretKey.trim(), secretValue, secretDesc.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node-secrets', nodeId] })
      setSecretKey('')
      setSecretValue('')
      setSecretDesc('')
      toast('Secret saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteSecretMutation = useMutation({
    mutationFn: (key: string) => nodeSecretsApi.delete(nodeId!, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node-secrets', nodeId] })
      toast('Secret deleted')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const addTagMutation = useMutation({
    mutationFn: () => fleetApi.addTag(nodeId!, tagKey, tagValue),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      setTagKey('')
      setTagValue('')
      toast('Tag added')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeTagMutation = useMutation({
    mutationFn: (key: string) => fleetApi.removeTag(nodeId!, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      toast('Tag removed')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const computeMutation = useMutation({
    mutationFn: () => driftApi.compute(nodeId!),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['drift-latest', nodeId] }), 3000)
    },
  })

  const cancelBootstrapMutation = useMutation({
    mutationFn: () => ansibleApi.cancelBootstrap(nodeId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      toast('Bootstrap cancelled')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const maintenanceMutation = useMutation({
    mutationFn: (enabled: boolean) => fleetApi.maintenanceMode(nodeId!, enabled),
    onSuccess: (_, enabled) => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      qc.invalidateQueries({ queryKey: ['nodes'] })
      toast(enabled ? 'Node entered maintenance mode' : 'Node exited maintenance mode')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  async function collectGrains() {
    if (!nodeId) return
    setCollectingGrains(true)
    setGrainTaskId(null)
    try {
      const resp = await api.post<{ task_id: string }>(`/api/v1/ansible/nodes/${nodeId}/collect-grains`)
      setGrainTaskId(resp.task_id)
      toast('Grain collection queued')
      setTimeout(() => refetch(), 8000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to queue grain collection'
      toast(msg, 'error')
    } finally {
      setCollectingGrains(false)
    }
  }

  async function rebootstrap() {
    if (!node || !rebootstrapIp.trim()) return
    setRebootstrapping(true)
    try {
      await api.post('/api/v1/ansible/bootstrap', {
        minion_id: node.minion_id,
        target_ip: rebootstrapIp.trim(),
      })
      toast('Re-bootstrap queued')
      setShowRebootstrap(false)
      setTimeout(() => refetch(), 3000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Re-bootstrap failed'
      toast(msg, 'error')
    } finally {
      setRebootstrapping(false)
    }
  }

  if (isLoading) return <Skeleton rows={8} />
  if (isError || !node) return <ErrorState message="Node not found" retry={refetch} />

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'drift', label: 'Drift' },
    { id: 'sbom', label: 'SBOM' },
    { id: 'executions', label: 'Executions' },
    { id: 'bootstrap-history', label: 'Bootstrap History' },
    { id: 'secrets', label: 'Secrets 🔑' },
  ]

  const chartData = driftHistory?.items
    .slice()
    .reverse()
    .map((d) => ({
      date: d.computed_at ? format(new Date(d.computed_at), 'MM/dd') : '',
      score: d.drift_score,
    }))

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">
              {node.hostname ?? node.minion_id}
            </h1>
            <StatusBadge status={node.status} />
            <DriftBadge score={node.drift_score} />
            {node.maintenance_mode && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200 font-medium">
                ⚙ Maintenance
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-1">
            {node.ip_address ?? 'IP unknown'} ·{' '}
            {node.last_seen_at
              ? `Last seen ${formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })}`
              : 'Never seen'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => maintenanceMutation.mutate(!node.maintenance_mode)}
            disabled={maintenanceMutation.isPending}
            className={`px-3 py-2 text-sm font-medium rounded-lg border shadow-sm disabled:opacity-50 transition-colors ${
              node.maintenance_mode
                ? 'bg-amber-100 text-amber-700 border-amber-300 hover:bg-amber-200'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
            }`}
            title={node.maintenance_mode ? 'Exit maintenance mode' : 'Enter maintenance mode'}
          >
            {maintenanceMutation.isPending
              ? '…'
              : node.maintenance_mode
              ? '⚙ Exit Maintenance'
              : '⚙ Maintenance'}
          </button>
          <button
            onClick={() => setShowSSH(true)}
            disabled={node.status !== 'online'}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 shadow-sm font-mono"
            title={node.status !== 'online' ? 'Node must be online' : 'Open SSH terminal'}
          >
            SSH
          </button>
          {vncEnabled && (
            <button
              onClick={() => setShowVNC(true)}
              disabled={node.status !== 'online'}
              className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 disabled:opacity-40 shadow-sm font-mono"
              title={node.status !== 'online' ? 'Node must be online' : 'Open VNC screen share'}
            >
              VNC
            </button>
          )}
          <Link to="/fleet" className="text-sm text-brand-600 hover:underline">← Fleet</Link>
        </div>
      </div>

      <div className="border-b border-gray-200 flex gap-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
            <h3 className="font-semibold text-gray-700">Hardware</h3>
            <dl className="space-y-1 text-sm">
              {(
                [
                  ['Model', node.hardware_model],
                  ['CPU Cores', node.cpu_cores != null ? String(node.cpu_cores) : null],
                  ['RAM', node.ram_gb != null ? `${node.ram_gb} GB` : null],
                  ['Storage', node.storage_gb != null ? `${node.storage_gb} GB` : null],
                ] as [string, string | null][]
              ).map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="font-medium">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
            <h3 className="font-semibold text-gray-700">OS</h3>
            <dl className="space-y-1 text-sm">
              {(
                [
                  ['Version', node.os_version],
                  ['Build', node.os_build],
                  ['First Seen', node.first_seen_at ? format(new Date(node.first_seen_at), 'PP') : null],
                ] as [string, string | null][]
              ).map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="font-medium">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </div>
          {/* Bootstrap status — only show if node has been bootstrapped or is bootstrapping */}
          {node.bootstrap_status !== 'unregistered' && (
            <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-gray-700">Bootstrap Status</h3>
                <div className="flex items-center gap-2">
                  {node.bootstrap_status === 'completed' && (
                    <>
                      <button
                        onClick={() => collectGrains()}
                        disabled={collectingGrains}
                        className="px-3 py-1.5 bg-brand-600 hover:bg-brand-700 text-white text-sm rounded-lg disabled:opacity-50"
                      >
                        {collectingGrains ? 'Collecting…' : 'Collect Grains Now'}
                      </button>
                      <button
                        onClick={() => { setRebootstrapIp(node.bootstrap_ip ?? node.ip_address ?? ''); setShowRebootstrap(true) }}
                        className="px-3 py-1.5 text-sm rounded-lg border border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100"
                      >
                        Re-bootstrap
                      </button>
                    </>
                  )}
                  {(node.bootstrap_status === 'failed') && (
                    <button
                      onClick={() => { setRebootstrapIp(node.bootstrap_ip ?? node.ip_address ?? ''); setShowRebootstrap(true) }}
                      className="px-3 py-1.5 text-sm rounded-lg border border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100"
                    >
                      Retry bootstrap
                    </button>
                  )}
                  {(node.bootstrap_status === 'bootstrapping' || node.bootstrap_status === 'pending') && (
                    <button
                      onClick={() => cancelBootstrapMutation.mutate()}
                      disabled={cancelBootstrapMutation.isPending}
                      className="text-xs text-red-600 hover:text-red-700 font-medium border border-red-200 bg-red-50 hover:bg-red-100 px-3 py-1 rounded-lg disabled:opacity-50 transition-colors"
                    >
                      {cancelBootstrapMutation.isPending ? 'Cancelling…' : 'Cancel bootstrap'}
                    </button>
                  )}
                </div>
              </div>

              {/* Re-bootstrap inline form */}
              {showRebootstrap && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg space-y-2">
                  <p className="text-xs text-amber-700 font-medium">This will re-run the bootstrap playbook. Existing node data is preserved.</p>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={rebootstrapIp}
                      onChange={(e) => setRebootstrapIp(e.target.value)}
                      placeholder="Target IP address"
                      className="flex-1 text-sm border border-amber-300 rounded px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400"
                    />
                    <button
                      onClick={rebootstrap}
                      disabled={rebootstrapping || !rebootstrapIp.trim()}
                      className="px-3 py-1 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
                    >
                      {rebootstrapping ? 'Queuing…' : 'Confirm'}
                    </button>
                    <button onClick={() => setShowRebootstrap(false)} className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50">
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className={`flex items-center gap-3 p-3 rounded-lg border ${BOOTSTRAP_STATUS_STYLE[node.bootstrap_status]?.bg ?? 'bg-gray-50 border-gray-200'}`}>
                <span className={`text-sm font-semibold ${BOOTSTRAP_STATUS_STYLE[node.bootstrap_status]?.colour ?? 'text-gray-600'}`}>
                  {BOOTSTRAP_STATUS_STYLE[node.bootstrap_status]?.label ?? node.bootstrap_status}
                </span>
                {node.bootstrap_ip && (
                  <span className="text-xs text-gray-500">via {node.bootstrap_ip}</span>
                )}
                {(node.bootstrap_status === 'bootstrapping' || node.bootstrap_status === 'pending') && (
                  <div className="w-3.5 h-3.5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin ml-auto" />
                )}
              </div>
              {node.bootstrap_error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 font-mono whitespace-pre-wrap">
                  {node.bootstrap_error}
                </div>
              )}
              {node.bootstrap_logs && (
                <details className="group">
                  <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 select-none">
                    View Ansible output
                  </summary>
                  <pre className="mt-2 text-xs font-mono bg-gray-900 text-gray-100 rounded-lg p-3 overflow-auto max-h-48 whitespace-pre-wrap">
                    {node.bootstrap_logs}
                  </pre>
                </details>
              )}

              {/* Grain collection task status */}
              {grainTaskId && grainTaskStatus && (
                <div className={`p-3 rounded-lg border text-xs font-mono ${
                  grainTaskStatus.state === 'SUCCESS' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' :
                  grainTaskStatus.state === 'FAILURE' ? 'bg-red-50 border-red-200 text-red-700' :
                  'bg-brand-50 border-brand-200 text-brand-700'
                }`}>
                  <div className="flex items-center gap-2">
                    {(grainTaskStatus.state === 'PENDING' || grainTaskStatus.state === 'STARTED') && (
                      <div className="w-3 h-3 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
                    )}
                    <span className="font-semibold">Grain collection: {grainTaskStatus.state}</span>
                  </div>
                  {grainTaskStatus.result != null && (
                    <pre className="mt-1 whitespace-pre-wrap">{JSON.stringify(grainTaskStatus.result, null, 2)}</pre>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-gray-700">Tags</h3>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-brand-300" /> auto (Salt)
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-gray-400" /> manual
                </span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              {node.tags.map((t) => (
                <span
                  key={t.key}
                  title={t.source === 'system' ? 'Auto-populated from Salt grains — read-only' : 'User-defined tag'}
                  className={`flex items-center gap-1 text-xs px-2 py-1 rounded border ${
                    t.source === 'system'
                      ? 'bg-brand-50 text-brand-700 border-brand-200'
                      : 'bg-gray-100 text-gray-700 border-gray-200'
                  }`}
                >
                  <span className="font-medium">{t.key}</span>
                  <span className="text-gray-400">=</span>
                  <span>{t.value}</span>
                  {t.source === 'user' && (
                    <button
                      onClick={() => removeTagMutation.mutate(t.key)}
                      disabled={removeTagMutation.isPending}
                      className="ml-1 text-gray-400 hover:text-red-500 disabled:opacity-40"
                      title="Remove tag"
                    >
                      ×
                    </button>
                  )}
                  {t.source === 'system' && (
                    <span className="ml-1 text-brand-400" title="Auto-populated">⊙</span>
                  )}
                </span>
              ))}
            </div>
            <form
              onSubmit={(e) => { e.preventDefault(); addTagMutation.mutate() }}
              className="flex gap-2"
            >
              <input
                placeholder="key"
                value={tagKey}
                onChange={(e) => setTagKey(e.target.value)}
                required
                className="w-28 text-sm border border-gray-300 rounded px-2 py-1"
              />
              <input
                placeholder="value"
                value={tagValue}
                onChange={(e) => setTagValue(e.target.value)}
                required
                className="w-28 text-sm border border-gray-300 rounded px-2 py-1"
              />
              <button
                type="submit"
                disabled={addTagMutation.isPending}
                className="px-3 py-1 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50"
              >
                Add Tag
              </button>
            </form>
          </div>
        </div>
      )}

      {tab === 'drift' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button
              onClick={() => computeMutation.mutate()}
              disabled={computeMutation.isPending}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50"
            >
              {computeMutation.isPending ? 'Queuing…' : 'Trigger Drift Compute'}
            </button>
          </div>

          {/* No drift record yet — but check for no baseline first */}
          {!latestDrift && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
              No baseline assigned — create one in{' '}
              <a href="/baselines" className="underline font-medium">Baselines</a>{' '}
              to start tracking drift.
            </div>
          )}

          {latestDrift && (() => {
            const missing = latestDrift.missing_packages ?? []
            const extra = latestDrift.extra_packages ?? []
            const mismatches = latestDrift.version_mismatches ?? []
            const totalDrifted = missing.length + mismatches.length + extra.length
            const isClean = latestDrift.drift_score === 0 && latestDrift.baseline_name != null

            return (
              <div className="space-y-4">
                {/* Score header */}
                <div className="bg-white rounded-lg border border-gray-200 p-4">
                  <div className="flex items-center gap-6 flex-wrap">
                    <div>
                      <p className="text-xs text-gray-500 uppercase">Drift Score</p>
                      <p className="text-3xl font-bold text-gray-900">{latestDrift.drift_score}</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 uppercase">Severity</p>
                      <p className="text-lg font-semibold capitalize">{latestDrift.severity}</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 uppercase">Baseline</p>
                      <p className="text-sm">{latestDrift.baseline_name ?? '—'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 uppercase">Computed</p>
                      <p className="text-sm">{format(new Date(latestDrift.computed_at), 'PP p')}</p>
                    </div>
                  </div>
                </div>

                {/* Compliance banner or summary chips */}
                {isClean ? (
                  <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-emerald-800 text-sm font-medium">
                    <span className="text-base">✓</span>
                    <span>In compliance — all packages match the baseline.</span>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2 items-center">
                    <span className="text-sm text-gray-600 font-medium">{totalDrifted} packages drifted</span>
                    {missing.length > 0 && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 border border-red-200">
                        <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                        {missing.length} missing
                      </span>
                    )}
                    {mismatches.length > 0 && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700 border border-amber-200">
                        <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
                        {mismatches.length} version mismatch{mismatches.length !== 1 ? 'es' : ''}
                      </span>
                    )}
                    {extra.length > 0 && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 border border-blue-200">
                        <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />
                        {extra.length} extra
                      </span>
                    )}
                  </div>
                )}

                {/* Missing packages */}
                {missing.length > 0 && (
                  <div className="bg-white rounded-lg border border-red-200 overflow-hidden">
                    <div className="flex items-center gap-2 px-4 py-2 bg-red-50 border-b border-red-200">
                      <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
                      <h4 className="text-sm font-semibold text-red-800">Missing Packages</h4>
                      <span className="ml-auto text-xs text-red-600">Expected by baseline but not installed</span>
                    </div>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                          <th className="px-4 py-2 text-left font-medium">Package</th>
                          <th className="px-4 py-2 text-left font-medium">Expected Version</th>
                          <th className="px-4 py-2 text-left font-medium">Severity Hint</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {missing.map((pkg, i) => (
                          <tr key={i} className="hover:bg-red-50/30">
                            <td className="px-4 py-2 font-mono font-medium text-gray-900">{pkg.name}</td>
                            <td className="px-4 py-2 font-mono text-gray-600">{pkg.required_version ?? '—'}</td>
                            <td className="px-4 py-2">
                              <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">required</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Version mismatches */}
                {mismatches.length > 0 && (
                  <div className="bg-white rounded-lg border border-amber-200 overflow-hidden">
                    <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                      <h4 className="text-sm font-semibold text-amber-800">Version Mismatches</h4>
                      <span className="ml-auto text-xs text-amber-600">Package present but wrong version</span>
                    </div>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                          <th className="px-4 py-2 text-left font-medium">Package</th>
                          <th className="px-4 py-2 text-left font-medium">Installed</th>
                          <th className="px-4 py-2 text-left font-medium">Expected</th>
                          <th className="px-4 py-2 text-left font-medium">Δ</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {mismatches.map((pkg, i) => (
                          <tr key={i} className="hover:bg-amber-50/30">
                            <td className="px-4 py-2 font-mono font-medium text-gray-900">{pkg.name}</td>
                            <td className="px-4 py-2 font-mono text-amber-700">{pkg.actual ?? '—'}</td>
                            <td className="px-4 py-2 font-mono text-gray-600">{pkg.expected ?? '—'}</td>
                            <td className="px-4 py-2 text-xs text-gray-400 font-mono">
                              {pkg.actual && pkg.expected ? `${pkg.actual} → ${pkg.expected}` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Extra packages */}
                {extra.length > 0 && (
                  <div className="bg-white rounded-lg border border-blue-200 overflow-hidden">
                    <div className="flex items-center gap-2 px-4 py-2 bg-blue-50 border-b border-blue-200">
                      <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                      <h4 className="text-sm font-semibold text-blue-800">Extra Packages</h4>
                      <span className="ml-auto text-xs text-blue-600">Installed but not in baseline</span>
                    </div>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                          <th className="px-4 py-2 text-left font-medium">Package</th>
                          <th className="px-4 py-2 text-left font-medium">Installed Version</th>
                          <th className="px-4 py-2 text-left font-medium">Note</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {extra.map((pkg, i) => (
                          <tr key={i} className="hover:bg-blue-50/30">
                            <td className="px-4 py-2 font-mono font-medium text-gray-900">{pkg.name}</td>
                            <td className="px-4 py-2 font-mono text-gray-600">{pkg.installed_version ?? '—'}</td>
                            <td className="px-4 py-2 text-xs text-gray-400">not in baseline</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Service drift */}
                {(latestDrift.service_drift ?? []).length > 0 && (
                  <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                    <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 border-b border-gray-200">
                      <h4 className="text-sm font-semibold text-gray-700">Service Drift</h4>
                    </div>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 uppercase border-b border-gray-100 bg-gray-50">
                          <th className="px-4 py-2 text-left font-medium">Service</th>
                          <th className="px-4 py-2 text-left font-medium">Expected</th>
                          <th className="px-4 py-2 text-left font-medium">Actual</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {latestDrift.service_drift.map((svc, i) => (
                          <tr key={i} className="hover:bg-gray-50">
                            <td className="px-4 py-2 font-mono font-medium text-gray-900">{svc.name}</td>
                            <td className="px-4 py-2 text-gray-600">{svc.expected}</td>
                            <td className="px-4 py-2 text-red-600">{svc.actual}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )
          })()}

          {chartData && chartData.length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h4 className="text-sm font-medium text-gray-700 mb-3">Drift History (30 days)</h4>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={chartData}>
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="score" stroke="#2563eb" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {tab === 'sbom' && (
        <div className="space-y-4">
          {/* Header: scan selector + trigger */}
          <div className="flex items-center gap-3 flex-wrap">
            {(sbomScanHistory?.items.length ?? 0) > 0 ? (
              <select
                className="text-sm border border-gray-300 rounded px-2 py-1 bg-white"
                value={activeScanId ?? ''}
                onChange={(e) => { setSelectedScanId(e.target.value); setCompPage(1) }}
              >
                {sbomScanHistory!.items.map((s, i) => (
                  <option key={s.id} value={s.id}>
                    {format(new Date(s.scanned_at), 'PP p')}{i === 0 ? ' (latest)' : ''}
                  </option>
                ))}
              </select>
            ) : null}
            <button
              className="ml-auto text-sm px-3 py-1.5 rounded bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
              disabled={triggeringScan}
              onClick={async () => {
                setTriggeringScan(true)
                try {
                  await api.post(`/api/v1/security/scan/${nodeId}?scanner=trivy`, {})
                  toast('SBOM scan queued', 'success')
                  setTimeout(() => qc.invalidateQueries({ queryKey: ['sbom-scans', nodeId] }), 5000)
                } catch {
                  toast('Failed to queue scan', 'error')
                } finally {
                  setTriggeringScan(false)
                }
              }}
            >
              {triggeringScan ? 'Queuing…' : '⟳ Scan now'}
            </button>
          </div>

          {activeScan ? (
            <>
              {/* Scan metadata */}
              <div className="bg-white rounded-lg border border-gray-200 p-4 flex gap-8 text-sm">
                <div>
                  <p className="text-gray-500">Scanned</p>
                  <p className="font-medium">{format(new Date(activeScan.scanned_at), 'PPpp')}</p>
                </div>
                <div>
                  <p className="text-gray-500">Format</p>
                  <p className="font-medium">{activeScan.format ?? 'cyclonedx'}</p>
                </div>
                <div>
                  <p className="text-gray-500">Components</p>
                  <p className="font-medium">{activeScan.component_count ?? '—'}</p>
                </div>
                {Object.keys(vulnsByPkg).length > 0 && (
                  <div>
                    <p className="text-gray-500">With CVEs</p>
                    <p className="font-medium text-red-600">{Object.keys(vulnsByPkg).length}</p>
                  </div>
                )}
              </div>

              {/* Search */}
              <input
                type="search"
                placeholder="Filter packages…"
                value={sbomFilter}
                onChange={(e) => { setSbomFilter(e.target.value); setCompPage(1) }}
                className="w-full text-sm border border-gray-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-500"
              />

              {/* Component table */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Licenses</th>
                      <th className="px-4 py-3">CVEs</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(components?.items ?? [])
                      .filter((c) => !sbomFilter || c.name.toLowerCase().includes(sbomFilter.toLowerCase()))
                      .map((c) => {
                        const sevs = vulnsByPkg[c.name] ?? []
                        const hasCrit = sevs.includes('CRITICAL')
                        const hasHigh = sevs.includes('HIGH')
                        return (
                          <tr key={c.id} className="hover:bg-gray-50">
                            <td className="px-4 py-2 font-mono text-xs">
                              {c.purl ? (
                                <span title={c.purl}>{c.name}</span>
                              ) : c.name}
                            </td>
                            <td className="px-4 py-2 text-gray-600">{c.version ?? '—'}</td>
                            <td className="px-4 py-2 text-gray-600">{c.component_type ?? '—'}</td>
                            <td className="px-4 py-2 text-gray-600">{c.licenses.join(', ') || '—'}</td>
                            <td className="px-4 py-2">
                              {sevs.length > 0 ? (
                                <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                                  hasCrit ? 'bg-red-100 text-red-700' :
                                  hasHigh ? 'bg-orange-100 text-orange-700' :
                                  'bg-yellow-100 text-yellow-700'
                                }`}>
                                  {sevs.length} {hasCrit ? 'CRITICAL' : hasHigh ? 'HIGH' : 'MEDIUM/LOW'}
                                </span>
                              ) : (
                                <span className="text-gray-300 text-xs">—</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                  </tbody>
                </table>
                {components && !sbomFilter && (
                  <Pagination page={compPage} total={components.total} perPage={components.per_page} onPage={setCompPage} />
                )}
              </div>
            </>
          ) : (
            <div className="text-center py-12 text-gray-500 text-sm">
              <p className="text-2xl mb-2">📦</p>
              <p>No SBOM scans yet.</p>
              <p className="text-xs mt-1">Click "Scan now" to trigger a Trivy scan.</p>
            </div>
          )}
        </div>
      )}

      {tab === 'executions' && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Triggered By</th>
                <th className="px-4 py-3">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {executions?.items.map((j) => (
                <tr key={j.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link to={`/executions/${j.id}`} className="text-brand-600 hover:underline">
                      {j.type}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      j.status === 'completed' ? 'bg-green-100 text-green-800' :
                      j.status === 'failed' ? 'bg-red-100 text-red-800' :
                      'bg-yellow-100 text-yellow-800'
                    }`}>
                      {j.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-600">{j.triggered_by}</td>
                  <td className="px-4 py-2 text-gray-500">
                    {j.started_at ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true }) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {executions && (
            <Pagination page={execPage} total={executions.total} perPage={executions.per_page} onPage={setExecPage} />
          )}
        </div>
      )}

      {showSSH && (
        <WebSSHTerminal
          nodeId={node.id}
          nodeName={node.hostname ?? node.minion_id}
          onClose={() => setShowSSH(false)}
        />
      )}

      {showVNC && (
        <VNCViewer
          nodeId={node.id}
          nodeName={node.hostname ?? node.minion_id}
          onClose={() => setShowVNC(false)}
        />
      )}

      {tab === 'secrets' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
            <span className="text-amber-500 text-lg mt-0.5">ℹ</span>
            <p className="text-sm text-amber-800">
              Secrets are injected into this node's Salt pillar and available as{' '}
              <code className="font-mono bg-amber-100 px-1 rounded">{'{{ pillar[\'key\'] }}'}</code>{' '}
              in Salt states and templates.
            </p>
          </div>

          {/* Existing secrets table */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-200">
              <p className="text-sm font-semibold text-gray-700">Stored Secrets</p>
              <p className="text-xs text-gray-400 mt-0.5">Values are write-only and never displayed.</p>
            </div>
            {!nodeSecrets || nodeSecrets.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400 text-sm">No secrets stored for this node.</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    <th className="px-4 py-3">Key</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3">Last Updated</th>
                    <th className="px-4 py-3 w-20"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {nodeSecrets.map((s) => (
                    <tr key={s.key} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono font-medium text-gray-900">{s.key}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{s.description ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {new Date(s.updated_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => deleteSecretMutation.mutate(s.key)}
                          disabled={deleteSecretMutation.isPending}
                          className="text-xs text-red-600 hover:text-red-700 font-medium disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Add secret form */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Add / Update Secret</p>
            <form
              onSubmit={(e) => { e.preventDefault(); addSecretMutation.mutate() }}
              className="space-y-3"
            >
              <div className="flex gap-3 flex-wrap">
                <div className="flex-1 min-w-32">
                  <label className="block text-xs text-gray-500 mb-1">Key</label>
                  <input
                    value={secretKey}
                    onChange={(e) => setSecretKey(e.target.value)}
                    placeholder="e.g. jenkins_slave_secret"
                    required
                    className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 font-mono focus:outline-none focus:ring-2 focus:ring-brand-400"
                  />
                </div>
                <div className="flex-1 min-w-40">
                  <label className="block text-xs text-gray-500 mb-1">Value</label>
                  <div className="relative">
                    <input
                      type={secretShowValue ? 'text' : 'password'}
                      value={secretValue}
                      onChange={(e) => setSecretValue(e.target.value)}
                      placeholder="Secret value"
                      required
                      className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 pr-16 focus:outline-none focus:ring-2 focus:ring-brand-400"
                    />
                    <button
                      type="button"
                      onClick={() => setSecretShowValue((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
                    >
                      {secretShowValue ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>
                <div className="flex-1 min-w-32">
                  <label className="block text-xs text-gray-500 mb-1">Description (optional)</label>
                  <input
                    value={secretDesc}
                    onChange={(e) => setSecretDesc(e.target.value)}
                    placeholder="Brief description"
                    className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-400"
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={addSecretMutation.isPending || !secretKey.trim() || !secretValue}
                  className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
                >
                  {addSecretMutation.isPending ? 'Saving…' : 'Save Secret'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {tab === 'bootstrap-history' && (
        <div className="space-y-3">
          {!bootstrapHistory || bootstrapHistory.items.length === 0 ? (
            <p className="text-sm text-gray-500">No bootstrap runs recorded for this node.</p>
          ) : (
            bootstrapHistory.items.map((run: BootstrapRunSummary) => (
              <div key={run.id} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <button
                  className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                  onClick={() =>
                    setExpandedRunId(expandedRunId === run.id ? null : run.id)
                  }
                >
                  <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded ${
                    run.status === 'completed'
                      ? 'bg-emerald-100 text-emerald-800'
                      : run.status === 'failed'
                      ? 'bg-red-100 text-red-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {run.status === 'completed' ? 'completed' : run.status === 'failed' ? 'failed' : 'running'}
                  </span>
                  <span className="text-sm text-gray-700 flex-1">
                    {format(new Date(run.started_at), 'PPpp')}
                    {run.finished_at && (
                      <span className="text-gray-400 ml-2">
                        — {formatDistanceToNow(new Date(run.started_at), { addSuffix: false })} duration
                      </span>
                    )}
                  </span>
                  {run.target_ip && (
                    <span className="text-xs text-gray-400">{run.target_ip}</span>
                  )}
                  <span className="text-xs text-gray-400">{expandedRunId === run.id ? '▲' : '▼'}</span>
                </button>
                {expandedRunId === run.id && (
                  <div className="border-t border-gray-200 p-4 space-y-2">
                    {run.error && (
                      <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2 font-mono">
                        {run.error}
                      </div>
                    )}
                    {run.has_stdout ? (
                      expandedRun?.id === run.id ? (
                        <pre className="text-xs font-mono bg-gray-900 text-gray-100 rounded-lg p-3 overflow-auto max-h-96 whitespace-pre-wrap">
                          {expandedRun.ansible_stdout}
                        </pre>
                      ) : (
                        <p className="text-xs text-gray-400 italic">Loading logs…</p>
                      )
                    ) : (
                      <p className="text-xs text-gray-400 italic">No stdout captured for this run.</p>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
          {bootstrapHistory && bootstrapHistory.total > bootstrapHistory.per_page && (
            <Pagination
              page={historyPage}
              total={bootstrapHistory.total}
              perPage={bootstrapHistory.per_page}
              onPage={setHistoryPage}
            />
          )}
        </div>
      )}
    </div>
  )
}
