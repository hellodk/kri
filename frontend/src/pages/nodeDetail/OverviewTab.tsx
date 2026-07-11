import { memo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fleetApi } from '../../api/fleet'
import { ansibleApi } from '../../api/ansible'
import { playbooksApi } from '../../api/playbooks'
import { vmsApi } from '../../api/vms'
import { api } from '../../api/client'
import { saltOpsApi } from '../../api/saltOps'
import { saltMasterBadge } from '../../lib/saltMasterHelpers'
import { LogPane } from '../../lib/LogPane'
import { formatISTDate } from '../../utils/time'
import { useToastStore } from '../../stores/toastStore'
import { BOOTSTRAP_STATUS_STYLE } from './utils'
import { ConnectivityPanel } from './ConnectivityPanel'
import { ResolvedCredentialPanel } from './ResolvedCredentialPanel'
import type { SaltMaster } from '../../api/saltMasters'
import type { NodeDetail as NodeDetailData } from '../../types'

export const OverviewTab = memo(function OverviewTab({
  node,
  nodeId,
  nodeMaster,
  canManage,
  showRebootstrap,
  setShowRebootstrap,
  rebootstrapIp,
  setRebootstrapIp,
  refetchNode,
}: {
  node: NodeDetailData
  nodeId: string
  nodeMaster: SaltMaster | undefined
  canManage: boolean
  showRebootstrap: boolean
  setShowRebootstrap: (v: boolean) => void
  rebootstrapIp: string
  setRebootstrapIp: (v: string) => void
  refetchNode: () => void
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [tagKey, setTagKey] = useState('')
  const [tagValue, setTagValue] = useState('')
  const [collectingGrains, setCollectingGrains] = useState(false)
  const [grainTaskId, setGrainTaskId] = useState<string | null>(null)
  const [rebootstrapping, setRebootstrapping] = useState(false)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const [runningAction, setRunningAction] = useState(false)
  const [deployingMonitoring, setDeployingMonitoring] = useState(false)
  const [rebootConfirm, setRebootConfirm] = useState(false)
  const [hardenConfirm, setHardenConfirm] = useState(false)
  const [hardeningAction, setHardeningAction] = useState(false)
  const [quickActionTaskId, setQuickActionTaskId] = useState<string | null>(null)
  const [quickActionPolling, setQuickActionPolling] = useState(false)
  const [quickTaskOutput, setQuickTaskOutput] = useState<{ status: string; stdout?: string; stderr?: string; reason?: string } | null>(null)

  const { data: grainTaskStatus } = useQuery({
    queryKey: ['grain-task', grainTaskId],
    queryFn: () => api.get<{ task_id: string; state: string; result?: unknown }>(`/api/v1/ansible/tasks/${grainTaskId}`),
    enabled: !!grainTaskId,
    refetchInterval: (q) => {
      const state = q.state.data?.state
      return state === 'PENDING' || state === 'STARTED' ? 2000 : false
    },
  })

  useQuery({
    queryKey: ['quick-action-task', quickActionTaskId],
    queryFn: () => api.get<{ task_id: string; state: string; result?: { status: string; stdout?: string; stderr?: string; reason?: string } }>(
      `/api/v1/ansible/tasks/${quickActionTaskId}`
    ),
    enabled: !!quickActionTaskId && quickActionPolling,
    refetchInterval: (q) => {
      const state = q.state.data?.state
      if (state === 'SUCCESS' || state === 'FAILURE') {
        setQuickActionPolling(false)
        if (q.state.data?.result) setQuickTaskOutput(q.state.data.result)
        return false
      }
      return 2000
    },
  })

  const { data: nodeVMs, isLoading: vmsLoading } = useQuery({
    queryKey: ['node-vms', nodeId],
    queryFn: () => vmsApi.listNodeVMs(nodeId),
    staleTime: 30_000,
    refetchInterval: 30_000,
    enabled: !!nodeId,
  })

  const addTagMutation = useMutation({
    mutationFn: () => fleetApi.addTag(nodeId, tagKey, tagValue),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      setTagKey('')
      setTagValue('')
      toast('Tag added')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeTagMutation = useMutation({
    mutationFn: (key: string) => fleetApi.removeTag(nodeId, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      toast('Tag removed')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const cancelBootstrapMutation = useMutation({
    mutationFn: () => ansibleApi.cancelBootstrap(nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      toast('Bootstrap cancelled')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  async function runSaltCommand(fn: string) {
    if (!node) return
    setRunningAction(true)
    setActionResult(null)
    setQuickTaskOutput(null)
    setQuickActionTaskId(null)
    setQuickActionPolling(false)
    try {
      const resp = await saltOpsApi.cmd(fn, [node.minion_id])
      setActionResult(`Queued: ${fn} (task ${resp.task_id})`)
      setQuickActionTaskId(resp.task_id)
      setQuickActionPolling(true)
      toast(`Salt command '${fn}' queued`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Command failed'
      setActionResult(`Error: ${msg}`)
      toast(msg, 'error')
    } finally {
      setRunningAction(false)
    }
  }

  async function deployNodeExporter() {
    if (!node || !nodeId) return
    setDeployingMonitoring(true)
    try {
      await playbooksApi.run('deploy_node_exporter.yml', 'node', nodeId, {})
      toast('node_exporter deployment queued')
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Deploy failed', 'error')
    } finally {
      setDeployingMonitoring(false)
    }
  }

  // Node-wide compute harden / unharden (#675). 'harden' is gated behind email
  // approval (PendingAction.DESTRUCTIVE); 'unharden' is the immediate reversal.
  // Params are empty — the backend applies a fixed Salt state whose never-disable
  // denylist is the safety boundary.
  async function requestHardenAction(actionType: 'harden' | 'unharden') {
    if (!nodeId) return
    setHardeningAction(true)
    try {
      const resp = await api.post<{ status: string; message: string }>(`/api/v1/nodes/${nodeId}/actions`, {
        action_type: actionType,
        params: {},
      })
      toast(resp.message || `${actionType} requested`)
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Action failed', 'error')
    } finally {
      setHardeningAction(false)
    }
  }

  async function collectGrains() {
    if (!nodeId) return
    setCollectingGrains(true)
    setGrainTaskId(null)
    try {
      const resp = await api.post<{ task_id: string }>(`/api/v1/ansible/nodes/${nodeId}/collect-grains`)
      setGrainTaskId(resp.task_id)
      toast('Grain collection queued')
      setTimeout(() => refetchNode(), 8000)
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
      setTimeout(() => refetchNode(), 3000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Re-bootstrap failed'
      toast(msg, 'error')
    } finally {
      setRebootstrapping(false)
    }
  }

  return (
    <div role="tabpanel" id="tabpanel-overview" aria-labelledby="tab-overview" className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {/* Salt-master panel — only shown when this node runs a master */}
      {nodeMaster && (() => {
        const badge = saltMasterBadge(nodeMaster.status)
        return (
          <div className="md:col-span-2 bg-indigo-50 border border-indigo-200 rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-2.5">
                {/* Indigo server icon */}
                <svg className="w-5 h-5 text-indigo-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
                </svg>
                <div>
                  <p className="text-sm font-semibold text-indigo-900">
                    Runs Salt Master
                    <span className="ml-2 text-xs font-normal text-indigo-600">
                      {nodeMaster.name}
                    </span>
                  </p>
                  <p className="text-xs text-indigo-600 mt-0.5">
                    {nodeMaster.address}
                    {nodeMaster.salt_version && (
                      <span className="ml-2 font-mono">v{nodeMaster.salt_version}</span>
                    )}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {/* Health badge — label + color (not color-only) */}
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold ${badge.bgClass} ${badge.textClass} border border-current/20`}
                  aria-label={`Salt-master health: ${badge.label}`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      nodeMaster.status === 'healthy' ? 'bg-emerald-600' :
                      nodeMaster.status === 'degraded' ? 'bg-amber-600' :
                      nodeMaster.status === 'unreachable' ? 'bg-red-600' : 'bg-gray-500'
                    }`}
                    aria-hidden="true"
                  />
                  {badge.label}
                </span>
                <Link
                  to="/overview?tab=salt-masters"
                  className="text-xs text-indigo-600 hover:text-indigo-800 font-medium underline underline-offset-2"
                >
                  Overview → Salt Masters →
                </Link>
              </div>
            </div>
          </div>
        )
      })()}

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
              ['First Seen', node.first_seen_at ? formatISTDate(node.first_seen_at) : null],
            ] as [string, string | null][]
          ).map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <dt className="text-gray-500">{label}</dt>
              <dd className="font-medium">{value ?? '—'}</dd>
            </div>
          ))}
        </dl>
      </div>
      {/* Bootstrap / re-bootstrap form. Rendered at the grid top level so it is
          available for any node regardless of bootstrap_status — including
          freshly-imported "unregistered" nodes whose Bootstrap Status card is
          hidden. The header Bootstrap button only flips showRebootstrap, so this
          must not be nested inside the status card or it never appears. */}
      {showRebootstrap && (
        <div className="md:col-span-2 p-4 bg-amber-50 border border-amber-200 rounded-lg space-y-2">
          <p className="text-xs text-amber-700 font-medium">
            {node.bootstrap_status === 'unregistered'
              ? 'This will run the bootstrap playbook on this node.'
              : 'This will re-run the bootstrap playbook. Existing node data is preserved.'}
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={rebootstrapIp}
              onChange={(e) => setRebootstrapIp(e.target.value)}
              placeholder="Target IP address"
              className="flex-1 text-sm border border-amber-300 rounded px-2 py-1 bg-white focus:outline-hidden focus:ring-2 focus:ring-amber-400"
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
          <details className="group" open={node.bootstrap_status === 'bootstrapping'}>
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 select-none">
              View Ansible output
            </summary>
            <div className="flex flex-col h-[28rem] mt-2">
              <LogPane
                raw={node.bootstrap_logs ?? ''}
                isLive={node.bootstrap_status === 'bootstrapping'}
                emptyText="No bootstrap output yet."
              />
            </div>
          </details>

          {/* Grain collection task status */}
          {grainTaskId && grainTaskStatus && (() => {
            // Derive actual outcome — Celery SUCCESS just means the task ran, not that it succeeded
            const grainOutcome = (() => {
              if (grainTaskStatus.state === 'PENDING' || grainTaskStatus.state === 'STARTED') return 'running'
              if (grainTaskStatus.state === 'FAILURE') return 'failed'
              // Task completed — check the result payload
              const result = grainTaskStatus.result as Record<string, unknown> | null
              if (result && result.status === 'error') return 'failed'
              if (result && result.status === 'ok') return 'ok'
              return grainTaskStatus.state === 'SUCCESS' ? 'ok' : 'failed'
            })()

            function cleanGrainError(reason: string): string {
              return reason
                .split('\n')
                .filter((line: string) => !line.startsWith('Warning:') && !line.startsWith('debug1:') && line.trim())
                .join('\n')
                .trim() || reason // fallback to original if filtering removes everything
            }

            const result = grainTaskStatus.result as Record<string, unknown> | null
            const httpStatus = result?.http_status as string | number | undefined
            const reason = result?.reason as string | undefined
            const via = result?.via as string | undefined

            return (
              <div className={`p-3 rounded-lg border text-xs font-mono ${
                grainOutcome === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' :
                grainOutcome === 'failed' ? 'bg-red-50 border-red-200 text-red-700' :
                'bg-brand-50 border-brand-200 text-brand-700'
              }`}>
                <div className="flex items-center gap-2">
                  {grainOutcome === 'running' && (
                    <div className="w-3 h-3 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
                  )}
                  <span className="font-semibold">
                    {grainOutcome === 'running' && 'Grain collection: running…'}
                    {grainOutcome === 'ok' && 'Grain collection: success'}
                    {grainOutcome === 'failed' && 'Grain collection: failed'}
                  </span>
                  {grainOutcome === 'ok' && httpStatus != null && (
                    <span className="ml-2 text-emerald-600 font-normal">
                      HTTP {httpStatus}{via ? ` · via ${via}` : ''}
                    </span>
                  )}
                </div>
                {grainOutcome === 'failed' && reason && (
                  <div className="mt-2 space-y-1">
                    <p className="font-semibold text-red-800 not-italic">Error:</p>
                    <pre className="whitespace-pre-wrap text-red-700">{cleanGrainError(reason)}</pre>
                    <p className="text-gray-500 font-sans not-italic mt-2">
                      kri fetches grains from the node&apos;s salt master (no SSH required). A failure usually
                      means the minion is offline or its key has not been accepted yet.
                    </p>
                  </div>
                )}
                {grainOutcome === 'failed' && !reason && (
                  <p className="text-gray-500 font-sans not-italic mt-1">
                    kri fetches grains from the node&apos;s salt master (no SSH required). A failure usually
                    means the minion is offline or its key has not been accepted yet.
                  </p>
                )}
              </div>
            )
          })()}
        </div>
      )}

      <ConnectivityPanel node={node} canManage={canManage} />

      <ResolvedCredentialPanel nodeId={nodeId} />

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

      {/* Quick Actions card */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 md:col-span-2">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Quick Actions</h3>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => runSaltCommand('state.apply')}
            disabled={runningAction}
            className="px-3 py-1.5 text-xs font-medium bg-brand-600 text-white rounded-md hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            Apply Highstate
          </button>
          <button
            onClick={() => runSaltCommand('test.ping')}
            disabled={runningAction}
            className="px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
          >
            Test Ping
          </button>
          <button
            onClick={() => runSaltCommand('saltutil.refresh_grains')}
            disabled={runningAction}
            className="px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
          >
            Refresh Grains
          </button>
          <button
            onClick={() => setRebootConfirm(true)}
            disabled={runningAction}
            className="px-3 py-1.5 text-xs font-medium bg-red-100 text-red-700 rounded-md hover:bg-red-200 disabled:opacity-50 transition-colors"
          >
            Reboot
          </button>
          <button
            onClick={() => setHardenConfirm(true)}
            disabled={hardeningAction}
            className="px-3 py-1.5 text-xs font-medium bg-amber-100 text-amber-800 rounded-md hover:bg-amber-200 disabled:opacity-50 transition-colors"
            title="Disable a conservative set of unneeded macOS services (Siri, Spotlight, analytics…). Requires email approval; fully reversible via Unharden."
          >
            Harden node
          </button>
          <button
            onClick={() => requestHardenAction('unharden')}
            disabled={hardeningAction}
            className="px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
            title="Re-enable everything Harden disabled and restore Spotlight indexing"
          >
            Unharden
          </button>
          <button
            onClick={deployNodeExporter}
            disabled={deployingMonitoring}
            className="px-3 py-1.5 text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg disabled:opacity-50 transition-colors"
            title="Install and start Prometheus node_exporter on this node"
          >
            {deployingMonitoring ? 'Deploying…' : 'Deploy Monitoring'}
          </button>
        </div>
        {rebootConfirm && (
          <div role="alertdialog" aria-label="Confirm reboot" className="mt-3 flex items-center gap-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            <span>Confirm reboot of {node.hostname ?? node.minion_id}?</span>
            <button onClick={() => { runSaltCommand('system.reboot'); setRebootConfirm(false) }}
              disabled={runningAction}
              className="px-2 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 font-medium">Yes, reboot</button>
            {/* autoFocus so keyboard focus lands on Cancel when confirmation strip appears */}
            <button autoFocus onClick={() => setRebootConfirm(false)}
              className="px-2 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200">Cancel</button>
          </div>
        )}
        {hardenConfirm && (
          <div role="alertdialog" aria-label="Confirm harden" className="mt-3 flex items-center gap-2 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
            <span>Harden {node.hostname ?? node.minion_id}? Disables a conservative, reversible set of macOS services. Sends an approval email.</span>
            <button onClick={() => { requestHardenAction('harden'); setHardenConfirm(false) }}
              disabled={hardeningAction}
              className="px-2 py-1 bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50 font-medium">Request approval</button>
            {/* autoFocus so keyboard focus lands on Cancel when confirmation strip appears */}
            <button autoFocus onClick={() => setHardenConfirm(false)}
              className="px-2 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200">Cancel</button>
          </div>
        )}
        {actionResult && (
          <div className="mt-3 p-2 text-xs font-mono bg-gray-50 dark:bg-gray-900 rounded text-gray-800 dark:text-gray-200 border border-gray-200 dark:border-gray-700">
            {actionResult}
            {quickActionPolling && (
              <span className="ml-2 text-gray-400 animate-pulse">polling…</span>
            )}
          </div>
        )}
        {quickTaskOutput && (
          <div className={`mt-2 p-3 text-xs rounded border ${quickTaskOutput.status === 'ok' ? 'bg-green-50 border-green-200 dark:bg-green-950 dark:border-green-800' : 'bg-red-50 border-red-200 dark:bg-red-950 dark:border-red-800'}`}>
            <div className={`font-semibold mb-1 ${quickTaskOutput.status === 'ok' ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'}`}>
              {quickTaskOutput.status === 'ok' ? '✓ Success' : '✗ Failed'}
            </div>
            {quickTaskOutput.stdout && (
              <pre className="font-mono whitespace-pre-wrap text-gray-800 dark:text-gray-200 bg-gray-50 dark:bg-gray-900 rounded p-2 mt-1 max-h-48 overflow-y-auto">
                {quickTaskOutput.stdout}
              </pre>
            )}
            {quickTaskOutput.stderr && (
              <pre className="font-mono whitespace-pre-wrap text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950 rounded p-2 mt-1 max-h-48 overflow-y-auto">
                {quickTaskOutput.stderr}
              </pre>
            )}
            {quickTaskOutput.reason && (
              <p className="text-gray-600 dark:text-gray-400 mt-1">{quickTaskOutput.reason}</p>
            )}
          </div>
        )}
      </div>

      {/* Virtual Machines Panel */}
      <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2">
        <h3 className="font-semibold text-gray-700 mb-3">Virtual Machines</h3>
        {vmsLoading && (
          <div className="space-y-2">
            <div className="h-4 w-32 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-24 bg-gray-200 rounded animate-pulse" />
          </div>
        )}
        {!vmsLoading && nodeVMs?.error && (
          <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">{nodeVMs.error}</p>
        )}
        {!vmsLoading && !nodeVMs?.error && nodeVMs?.vms.length === 0 && (
          <p className="text-sm text-gray-500">tart is not installed or no VMs are running on this node.</p>
        )}
        {!vmsLoading && !nodeVMs?.error && nodeVMs?.vms && nodeVMs.vms.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th scope="col" className="text-left px-3 py-2 font-semibold text-gray-700">Name</th>
                  <th scope="col" className="text-left px-3 py-2 font-semibold text-gray-700">State</th>
                  <th scope="col" className="text-left px-3 py-2 font-semibold text-gray-700">CPU</th>
                  <th scope="col" className="text-left px-3 py-2 font-semibold text-gray-700">Memory</th>
                  <th scope="col" className="text-left px-3 py-2 font-semibold text-gray-700">Source</th>
                </tr>
              </thead>
              <tbody>
                {nodeVMs.vms.map((vm) => (
                  <tr key={vm.name} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-3 py-2 font-medium text-gray-900">{vm.name}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
                        vm.state === 'Running' ? 'bg-emerald-100 text-emerald-800' :
                        vm.state === 'Stopped' ? 'bg-gray-100 text-gray-800' :
                        vm.state === 'Suspended' ? 'bg-yellow-100 text-yellow-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {vm.state}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-600">{vm.cpu ? `${vm.cpu} cores` : '—'}</td>
                    <td className="px-3 py-2 text-gray-600">{vm.memory ? `${vm.memory} MB` : '—'}</td>
                    <td className="px-3 py-2 text-gray-600 text-xs font-mono">{vm.source || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
})
