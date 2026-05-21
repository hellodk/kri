import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { driftApi } from '../api/drift'
import { sbomApi } from '../api/sbom'
import { executionsApi } from '../api/executions'
import { ansibleApi, type BootstrapRunSummary } from '../api/ansible'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow, format } from 'date-fns'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useToastStore } from '../stores/toastStore'

const BOOTSTRAP_STATUS_STYLE: Record<string, { label: string; colour: string; bg: string }> = {
  unregistered: { label: 'Not bootstrapped', colour: 'text-gray-500', bg: 'bg-gray-50 border-gray-200' },
  pending:      { label: 'Queued',           colour: 'text-gray-600', bg: 'bg-gray-50 border-gray-200' },
  bootstrapping:{ label: 'Running…',         colour: 'text-brand-600', bg: 'bg-brand-50 border-brand-200' },
  completed:    { label: 'Completed',        colour: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  failed:       { label: 'Failed',           colour: 'text-red-700', bg: 'bg-red-50 border-red-200' },
}

type Tab = 'overview' | 'drift' | 'sbom' | 'executions' | 'bootstrap-history'

export function NodeDetail() {
  const { nodeId } = useParams<{ nodeId: string }>()
  const [tab, setTab] = useState<Tab>('overview')
  const [execPage, setExecPage] = useState(1)
  const [compPage, setCompPage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [tagKey, setTagKey] = useState('')
  const [tagValue, setTagValue] = useState('')
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

  const { data: sbomScan } = useQuery({
    queryKey: ['sbom-latest', nodeId],
    queryFn: () => sbomApi.latestScan(nodeId!),
    staleTime: 300_000,
    enabled: !!nodeId && tab === 'sbom',
  })

  const { data: components } = useQuery({
    queryKey: ['sbom-components', nodeId, sbomScan?.id, compPage],
    queryFn: () => sbomApi.components(nodeId!, sbomScan!.id, { page: compPage, per_page: 100 }),
    staleTime: 300_000,
    enabled: !!sbomScan?.id,
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

  if (isLoading) return <Skeleton rows={8} />
  if (isError || !node) return <ErrorState message="Node not found" retry={refetch} />

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'drift', label: 'Drift' },
    { id: 'sbom', label: 'SBOM' },
    { id: 'executions', label: 'Executions' },
    { id: 'bootstrap-history', label: 'Bootstrap History' },
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
          </div>
          <p className="text-sm text-gray-500 mt-1">
            {node.ip_address ?? 'IP unknown'} ·{' '}
            {node.last_seen_at
              ? `Last seen ${formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })}`
              : 'Never seen'}
          </p>
        </div>
        <Link to="/fleet" className="text-sm text-brand-600 hover:underline">← Fleet</Link>
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
          {latestDrift && (
            <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
              <div className="flex items-center gap-4">
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
              </div>
              {[
                { title: 'Missing Packages', items: latestDrift.missing_packages },
                { title: 'Extra Packages', items: latestDrift.extra_packages },
                { title: 'Version Mismatches', items: latestDrift.version_mismatches },
              ].map(({ title, items }) =>
                items.length > 0 ? (
                  <div key={title}>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">{title}</h4>
                    <ul className="text-sm bg-gray-50 rounded p-3 space-y-1">
                      {items.map((item, i) => (
                        <li key={i} className="font-mono text-gray-700">
                          {JSON.stringify(item)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null
              )}
            </div>
          )}
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
          {sbomScan ? (
            <>
              <div className="bg-white rounded-lg border border-gray-200 p-4 flex gap-8 text-sm">
                <div>
                  <p className="text-gray-500">Scanned</p>
                  <p className="font-medium">{format(new Date(sbomScan.scanned_at), 'PPpp')}</p>
                </div>
                <div>
                  <p className="text-gray-500">Syft</p>
                  <p className="font-medium">{sbomScan.syft_version ?? '—'}</p>
                </div>
                <div>
                  <p className="text-gray-500">Components</p>
                  <p className="font-medium">{sbomScan.component_count ?? '—'}</p>
                </div>
              </div>
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Licenses</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {components?.items.map((c) => (
                      <tr key={c.id} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-mono text-xs">{c.name}</td>
                        <td className="px-4 py-2 text-gray-600">{c.version ?? '—'}</td>
                        <td className="px-4 py-2 text-gray-600">{c.component_type ?? '—'}</td>
                        <td className="px-4 py-2 text-gray-600">{c.licenses.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {components && (
                  <Pagination page={compPage} total={components.total} perPage={components.per_page} onPage={setCompPage} />
                )}
              </div>
            </>
          ) : (
            <p className="text-gray-500 text-sm">No SBOM scans yet for this node.</p>
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
