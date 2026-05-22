import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { differenceInDays, formatDistanceToNow, parseISO } from 'date-fns'
import {
  iosTrackingApi,
  type IOSNode,
  type Certificate,
  type JenkinsAgent,
  type AddCertBody,
  type UpsertJenkinsBody,
} from '../api/iosTracking'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { useToastStore } from '../stores/toastStore'

const CERT_TYPES = ['code_signing', 'provisioning', 'distribution', 'other']

// ── Helpers ───────────────────────────────────────────────────────────

function daysUntil(dateStr: string | null) {
  if (!dateStr) return null
  return differenceInDays(parseISO(dateStr), new Date())
}

function expiryClass(dateStr: string | null) {
  const d = daysUntil(dateStr)
  if (d === null) return ''
  if (d < 0) return 'text-red-700 font-semibold'
  if (d < 30) return 'text-red-600 font-medium'
  if (d < 60) return 'text-amber-600 font-medium'
  return 'text-gray-700'
}

function JenkinsStatusDot({ status }: { status: string | null }) {
  if (!status) return <span className="text-gray-300 text-xs">—</span>
  const cls =
    status === 'online'
      ? 'bg-green-500'
      : status === 'offline'
      ? 'bg-red-500'
      : 'bg-gray-400'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cls}`} />
      <span className="text-xs capitalize text-gray-700">{status}</span>
    </span>
  )
}

// ── Tab: Fleet Overview ───────────────────────────────────────────────

function FleetOverviewTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['ios-nodes'],
    queryFn: iosTrackingApi.listNodes,
    staleTime: 30_000,
  })

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      {isLoading ? (
        <Skeleton rows={6} />
      ) : isError ? (
        <ErrorState message="Failed to load iOS fleet data" retry={refetch} />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
              <th className="px-4 py-3">Hostname</th>
              <th className="px-4 py-3">macOS</th>
              <th className="px-4 py-3">Xcode</th>
              <th className="px-4 py-3">Jenkins</th>
              <th className="px-4 py-3">Certs</th>
              <th className="px-4 py-3">Next Expiry</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data?.items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-400 text-sm">
                  No nodes registered
                </td>
              </tr>
            )}
            {data?.items.map((node: IOSNode) => (
              <tr key={node.node_id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <span className="font-medium text-gray-800">
                    {node.hostname || node.minion_id}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600 font-mono text-xs">
                  {node.macos_version ?? <span className="text-gray-400">—</span>}
                </td>
                <td className="px-4 py-3 text-gray-600 font-mono text-xs">
                  {node.xcode_version ?? <span className="text-gray-400">—</span>}
                </td>
                <td className="px-4 py-3">
                  <JenkinsStatusDot status={node.jenkins_status} />
                </td>
                <td className="px-4 py-3 text-gray-700">{node.cert_count}</td>
                <td className={`px-4 py-3 text-xs ${expiryClass(node.next_cert_expiry)}`}>
                  {node.next_cert_expiry ?? <span className="text-gray-400">—</span>}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    to={`/nodes/${node.node_id}`}
                    className="text-brand-600 hover:underline text-xs font-medium"
                  >
                    View
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Add Cert Modal ────────────────────────────────────────────────────

function AddCertForm({
  nodeId,
  onClose,
}: {
  nodeId: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [form, setForm] = useState<AddCertBody>({
    name: '',
    cert_type: 'code_signing',
    team_id: '',
    expiry_date: '',
    fingerprint: '',
  })

  const mut = useMutation({
    mutationFn: () => iosTrackingApi.addCertificate(nodeId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ios-certs'] })
      qc.invalidateQueries({ queryKey: ['ios-nodes'] })
      toast('Certificate added', 'success')
      onClose()
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  return (
    <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3 mb-4">
      <h3 className="text-sm font-semibold text-gray-800">Add Certificate</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
          <select
            value={form.cert_type}
            onChange={(e) => setForm({ ...form, cert_type: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            {CERT_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Team ID</label>
          <input
            type="text"
            value={form.team_id ?? ''}
            onChange={(e) => setForm({ ...form, team_id: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Expiry Date</label>
          <input
            type="date"
            value={form.expiry_date}
            onChange={(e) => setForm({ ...form, expiry_date: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Fingerprint (optional)</label>
        <input
          type="text"
          value={form.fingerprint ?? ''}
          onChange={(e) => setForm({ ...form, fingerprint: e.target.value })}
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 font-mono"
        />
      </div>
      <div className="flex gap-2">
        <button
          disabled={!form.name || !form.expiry_date || mut.isPending}
          onClick={() => mut.mutate()}
          className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
        >
          {mut.isPending ? 'Adding…' : 'Add Certificate'}
        </button>
        <button
          onClick={onClose}
          className="px-4 py-1.5 rounded-lg border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Tab: Certificates ─────────────────────────────────────────────────

function CertificatesTab() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [typeFilter, setTypeFilter] = useState('')
  const [addingForNode, setAddingForNode] = useState<string | null>(null)

  const { data: nodesData } = useQuery({
    queryKey: ['ios-nodes'],
    queryFn: iosTrackingApi.listNodes,
  })

  const { data: expiringData, isLoading, isError, refetch } = useQuery({
    queryKey: ['ios-certs'],
    queryFn: () => iosTrackingApi.getExpiringCerts(365),
    staleTime: 30_000,
  })

  const deleteMut = useMutation({
    mutationFn: iosTrackingApi.deleteCertificate,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ios-certs'] })
      qc.invalidateQueries({ queryKey: ['ios-nodes'] })
      toast('Certificate deleted', 'success')
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  const nodeMap = Object.fromEntries(
    (nodesData?.items ?? []).map((n) => [n.node_id, n.hostname || n.minion_id])
  )

  const certs = (expiringData?.items ?? []).filter(
    (c) => !typeFilter || c.cert_type === typeFilter
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">All types</option>
          {CERT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {expiringData && (
          <span className="text-sm text-gray-500">
            {certs.length} cert{certs.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Add cert form */}
      {addingForNode && (
        <AddCertForm nodeId={addingForNode} onClose={() => setAddingForNode(null)} />
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={6} />
        ) : isError ? (
          <ErrorState message="Failed to load certificates" retry={refetch} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Node</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Team ID</th>
                <th className="px-4 py-3">Expiry</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {certs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No certificates found
                  </td>
                </tr>
              )}
              {certs.map((cert: Certificate) => (
                <tr key={cert.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-700 text-xs">
                    {nodeMap[cert.node_id] ?? cert.node_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-800">{cert.name}</td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 text-xs font-medium">
                      {cert.cert_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">
                    {cert.team_id ?? <span className="text-gray-400">—</span>}
                  </td>
                  <td className={`px-4 py-3 text-xs ${expiryClass(cert.expiry_date)}`}>
                    {cert.expiry_date}
                    {(() => {
                      const d = daysUntil(cert.expiry_date)
                      if (d === null) return null
                      if (d < 0) return <span className="ml-1 text-red-600">(expired)</span>
                      if (d < 60) return <span className="ml-1">({d}d)</span>
                      return null
                    })()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => setAddingForNode(cert.node_id)}
                        className="text-brand-600 hover:text-brand-800 text-xs font-medium"
                      >
                        Add cert
                      </button>
                      <button
                        onClick={() => {
                          if (confirm('Delete this certificate?')) {
                            deleteMut.mutate(cert.id)
                          }
                        }}
                        className="text-red-500 hover:text-red-700 text-xs font-medium"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Jenkins Config Modal ──────────────────────────────────────────────

function JenkinsConfigForm({
  nodeId,
  existing,
  onClose,
}: {
  nodeId: string
  existing: JenkinsAgent | null
  onClose: () => void
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [form, setForm] = useState<UpsertJenkinsBody>({
    jenkins_url: existing?.jenkins_url ?? '',
    agent_name: existing?.agent_name ?? '',
  })

  const mut = useMutation({
    mutationFn: () => iosTrackingApi.upsertJenkinsAgent(nodeId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ios-jenkins'] })
      qc.invalidateQueries({ queryKey: ['ios-nodes'] })
      toast('Jenkins agent configured', 'success')
      onClose()
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  return (
    <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3 mb-4">
      <h3 className="text-sm font-semibold text-gray-800">Configure Jenkins Agent</h3>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Jenkins URL</label>
        <input
          type="url"
          value={form.jenkins_url}
          onChange={(e) => setForm({ ...form, jenkins_url: e.target.value })}
          placeholder="https://jenkins.example.com"
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Agent Name</label>
        <input
          type="text"
          value={form.agent_name}
          onChange={(e) => setForm({ ...form, agent_name: e.target.value })}
          placeholder="mac-mini-agent-01"
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>
      <div className="flex gap-2">
        <button
          disabled={!form.jenkins_url || !form.agent_name || mut.isPending}
          onClick={() => mut.mutate()}
          className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
        >
          {mut.isPending ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={onClose}
          className="px-4 py-1.5 rounded-lg border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Tab: Jenkins Agents ───────────────────────────────────────────────

function JenkinsAgentsTab() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [configuringNodeId, setConfiguringNodeId] = useState<string | null>(null)

  const { data: nodesData, isLoading, isError, refetch } = useQuery({
    queryKey: ['ios-nodes'],
    queryFn: iosTrackingApi.listNodes,
    staleTime: 30_000,
  })

  const checkMut = useMutation({
    mutationFn: (nodeId: string) => iosTrackingApi.checkJenkinsNow(nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ios-nodes'] })
      toast('Jenkins status refreshed', 'success')
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  // Filter only nodes that have jenkins_status configured
  const nodesWithJenkins = (nodesData?.items ?? []).filter(
    (n) => n.jenkins_status !== null
  )

  return (
    <div className="space-y-4">
      {configuringNodeId && (
        <JenkinsConfigForm
          nodeId={configuringNodeId}
          existing={null}
          onClose={() => setConfiguringNodeId(null)}
        />
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={6} />
        ) : isError ? (
          <ErrorState message="Failed to load Jenkins agents" retry={refetch} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Node</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {nodesWithJenkins.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No Jenkins agents configured.{' '}
                    <button
                      onClick={() => setConfiguringNodeId('__new__')}
                      className="text-brand-600 hover:underline"
                    >
                      Configure one now
                    </button>
                  </td>
                </tr>
              )}
              {nodesWithJenkins.map((node: IOSNode) => (
                <tr key={node.node_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">
                    {node.hostname || node.minion_id}
                  </td>
                  <td className="px-4 py-3">
                    <JenkinsStatusDot status={node.jenkins_status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => checkMut.mutate(node.node_id)}
                        disabled={checkMut.isPending}
                        className="text-brand-600 hover:text-brand-800 text-xs font-medium disabled:opacity-50"
                      >
                        Check now
                      </button>
                      <button
                        onClick={() => setConfiguringNodeId(node.node_id)}
                        className="text-gray-600 hover:text-gray-800 text-xs font-medium"
                      >
                        Configure
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* All nodes — allow configuring any */}
      {nodesData && nodesData.items.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-2">Configure Jenkins agent for any node:</p>
          <div className="flex flex-wrap gap-2">
            {nodesData.items.map((n) => (
              <button
                key={n.node_id}
                onClick={() => setConfiguringNodeId(n.node_id)}
                className="px-2 py-1 rounded border border-gray-300 text-xs text-gray-700 hover:bg-gray-100 transition-colors"
              >
                {n.hostname || n.minion_id}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────

const TABS = [
  { id: 'overview', label: 'Fleet Overview' },
  { id: 'certs', label: 'Certificates' },
  { id: 'jenkins', label: 'Jenkins Agents' },
]

export function IOSTrackingPage() {
  const [activeTab, setActiveTab] = useState<string>('overview')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">iOS Fleet</h1>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-brand-600 text-brand-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === 'overview' && <FleetOverviewTab />}
      {activeTab === 'certs' && <CertificatesTab />}
      {activeTab === 'jenkins' && <JenkinsAgentsTab />}
    </div>
  )
}
