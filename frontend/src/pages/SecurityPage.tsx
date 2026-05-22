import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useToastStore } from '../stores/toastStore'

// ── Types ────────────────────────────────────────────────────────────────────

interface NodeSecuritySummary {
  node_id: string
  minion_id: string
  hostname: string | null
  status: string
  has_sbom: boolean
  vulnerabilities: { critical: number; high: number; medium: number; low: number }
  license_risks: { high: number; medium: number; unknown: number }
  last_scanned_at: string | null
  risk_level: 'critical' | 'high' | 'medium' | 'low' | 'clean' | 'unscanned'
}

interface VulnFinding {
  id: string
  cve_id: string
  package_name: string
  package_version: string | null
  severity: string
  cvss_score: number | null
  fixed_version: string | null
  description: string | null
  reference_url: string | null
  scanner: string
  scanned_at: string
}

interface LicenseFinding {
  id: string
  package_name: string
  package_version: string | null
  license_id: string
  risk: string
  scanner: string
  scanned_at: string
}

interface NodeDetail {
  node_id: string
  vulnerabilities: VulnFinding[]
  license_findings: LicenseFinding[]
}

interface IntegrationStatus {
  trivy: { available: boolean; configured: boolean }
  cxone: { available: boolean; configured: boolean }
  sonarqube: { available: boolean; configured: boolean }
}

// ── Severity / Risk badges ───────────────────────────────────────────────────

const RISK_COLORS: Record<string, string> = {
  critical: 'bg-red-600 text-white',
  high: 'bg-orange-500 text-white',
  medium: 'bg-amber-500 text-white',
  low: 'bg-blue-500 text-white',
  clean: 'bg-emerald-500 text-white',
  unscanned: 'bg-gray-300 text-gray-700',
}

const LIC_RISK_COLORS: Record<string, string> = {
  high: 'bg-red-100 text-red-800 border-red-300',
  medium: 'bg-amber-100 text-amber-800 border-amber-300',
  unknown: 'bg-gray-100 text-gray-600 border-gray-300',
  allowed: 'bg-emerald-100 text-emerald-800 border-emerald-200',
}

function RiskBadge({ risk }: { risk: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${RISK_COLORS[risk] ?? RISK_COLORS.unscanned}`}>
      {risk.toUpperCase()}
    </span>
  )
}

// ── Integration status bar ────────────────────────────────────────────────────

function IntegrationBar({ status }: { status: IntegrationStatus | undefined }) {
  const tools = [
    { name: 'Trivy', key: 'trivy' as const },
    { name: 'CxOne', key: 'cxone' as const },
    { name: 'SonarQube', key: 'sonarqube' as const },
  ]
  return (
    <div className="flex items-center gap-4 text-xs">
      {tools.map(({ name, key }) => {
        const s = status?.[key]
        const dot = !s ? 'bg-gray-300' : s.available ? 'bg-emerald-500' : s.configured ? 'bg-amber-500' : 'bg-gray-300'
        const label = !s ? '-' : s.available ? 'connected' : s.configured ? 'unreachable' : 'not configured'
        return (
          <div key={key} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${dot}`} />
            <span className="text-gray-600 font-medium">{name}</span>
            <span className="text-gray-400">{label}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Node detail drawer ─────────────────────────────────────────────────────────

function NodeSecurityDrawer({ nodeId, onClose }: { nodeId: string; onClose: () => void }) {
  const [tab, setTab] = useState<'vulns' | 'licenses'>('vulns')

  const { data, isLoading } = useQuery({
    queryKey: ['security-node-detail', nodeId],
    queryFn: () => api.get<NodeDetail>(`/api/v1/security/nodes/${nodeId}`),
    staleTime: 60_000,
  })

  const vulnsBySeverity = (sev: string) =>
    data?.vulnerabilities.filter(v => v.severity === sev) ?? []

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <div className="w-full max-w-3xl bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-gray-50 shrink-0">
          <h2 className="text-base font-bold text-gray-900">Security Findings</h2>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded-lg text-lg">x</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 shrink-0">
          {(['vulns', 'licenses'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-5 py-2.5 text-sm font-medium border-b-2 -mb-px ${
                tab === t ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {t === 'vulns'
                ? `Vulnerabilities (${data?.vulnerabilities.length ?? 0})`
                : `Licenses (${data?.license_findings.length ?? 0})`}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-gray-400">Loading...</div>
          ) : tab === 'vulns' ? (
            <div>
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => {
                const items = vulnsBySeverity(sev)
                if (!items.length) return null
                return (
                  <div key={sev}>
                    <div className={`px-4 py-1.5 text-xs font-bold uppercase tracking-wide border-b ${
                      sev === 'CRITICAL' ? 'bg-red-50 text-red-700 border-red-100' :
                      sev === 'HIGH' ? 'bg-orange-50 text-orange-700 border-orange-100' :
                      sev === 'MEDIUM' ? 'bg-amber-50 text-amber-700 border-amber-100' :
                      'bg-blue-50 text-blue-700 border-blue-100'
                    }`}>{sev} ({items.length})</div>
                    {items.map(v => (
                      <div key={v.id} className="px-4 py-3 border-b border-gray-100 hover:bg-gray-50">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              {v.reference_url ? (
                                <a href={v.reference_url} target="_blank" rel="noopener noreferrer"
                                  className="text-sm font-mono font-semibold text-brand-600 hover:underline">
                                  {v.cve_id}
                                </a>
                              ) : (
                                <span className="text-sm font-mono font-semibold text-gray-800">{v.cve_id}</span>
                              )}
                              <span className="text-sm text-gray-600">{v.package_name} {v.package_version}</span>
                            </div>
                            {v.description && (
                              <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{v.description}</p>
                            )}
                            {v.fixed_version && (
                              <p className="text-xs text-emerald-600 mt-0.5">Fix available: {v.fixed_version}</p>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {v.cvss_score != null && (
                              <span className="text-xs text-gray-500 font-mono">CVSS {v.cvss_score.toFixed(1)}</span>
                            )}
                            <span className="text-xs text-gray-400">{v.scanner}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              })}
              {!data?.vulnerabilities.length && (
                <div className="flex flex-col items-center justify-center h-32 text-gray-400 gap-2">
                  <span className="text-2xl">v</span>
                  <p className="text-sm">No vulnerabilities found</p>
                </div>
              )}
            </div>
          ) : (
            <div>
              {(['high', 'medium', 'unknown', 'allowed'] as const).map(risk => {
                const items = data?.license_findings.filter(l => l.risk === risk) ?? []
                if (!items.length) return null
                return (
                  <div key={risk}>
                    <div className={`px-4 py-1.5 text-xs font-bold uppercase tracking-wide border-b ${
                      risk === 'high' ? 'bg-red-50 text-red-700 border-red-100' :
                      risk === 'medium' ? 'bg-amber-50 text-amber-700 border-amber-100' :
                      risk === 'unknown' ? 'bg-gray-50 text-gray-600 border-gray-100' :
                      'bg-emerald-50 text-emerald-700 border-emerald-100'
                    }`}>{risk} risk ({items.length})</div>
                    {items.map(l => (
                      <div key={l.id} className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 hover:bg-gray-50">
                        <div>
                          <span className="text-sm font-medium text-gray-800">{l.package_name}</span>
                          {l.package_version && <span className="text-xs text-gray-400 ml-1.5">{l.package_version}</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded border font-medium ${LIC_RISK_COLORS[l.risk] ?? LIC_RISK_COLORS.unknown}`}>
                            {l.license_id}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              })}
              {!data?.license_findings.length && (
                <div className="flex flex-col items-center justify-center h-32 text-gray-400 gap-2">
                  <span className="text-2xl">v</span>
                  <p className="text-sm">No license issues found</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Types for PAM sessions ────────────────────────────────────────────────────

interface SSHSessionRow {
  id: string
  node_id: string
  user_id: string | null
  started_at: string
  ended_at: string | null
  source_ip: string | null
  credential_source: string
  status: string
  alert_count: number
  target_ip: string | null
  ssh_user: string | null
}

interface SecurityEventRow {
  id: string
  session_id: string | null
  node_id: string | null
  event_type: string
  command: string | null
  severity: string
  detail: string | null
  created_at: string
}

const EVENT_SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
}

const SESSION_STATUS_COLORS: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-800',
  closed: 'bg-gray-100 text-gray-600',
  killed: 'bg-red-100 text-red-800',
  timed_out: 'bg-amber-100 text-amber-700',
  blocked: 'bg-orange-100 text-orange-800',
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function SecurityPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const { data: dashboard } = useQuery({
    queryKey: ['security-dashboard'],
    queryFn: () => api.get<any>('/api/v1/security/dashboard'),
    staleTime: 60_000,
  })

  const { data: activeSessions } = useQuery({
    queryKey: ['ssh-sessions-active'],
    queryFn: () => api.get<{ items: SSHSessionRow[] }>('/api/v1/ssh/sessions?status=active&limit=20'),
    refetchInterval: 10_000,
  })

  const { data: recentEvents } = useQuery({
    queryKey: ['security-events-recent'],
    queryFn: () => api.get<{ items: SecurityEventRow[] }>('/api/v1/ssh/events?limit=20'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const { data: nodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['security-nodes'],
    queryFn: () => api.get<{ items: NodeSecuritySummary[]; total: number }>('/api/v1/security/nodes'),
    staleTime: 30_000,
  })

  const { data: integrations } = useQuery({
    queryKey: ['security-integration-status'],
    queryFn: () => api.get<IntegrationStatus>('/api/v1/security/integration-status'),
    staleTime: 120_000,
  })

  const scanAllMutation = useMutation({
    mutationFn: (scanner: string) => api.post(`/api/v1/security/scan-all?scanner=${scanner}`, {}),
    onSuccess: () => {
      toast('Scans queued for all nodes')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['security-nodes'] }), 30_000)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const scanNodeMutation = useMutation({
    mutationFn: ({ nodeId, scanner }: { nodeId: string; scanner: string }) =>
      api.post(`/api/v1/security/scan/${nodeId}?scanner=${scanner}`, {}),
    onSuccess: (_, { nodeId }) => {
      toast('Scan queued')
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['security-nodes'] })
        qc.invalidateQueries({ queryKey: ['security-node-detail', nodeId] })
      }, 30_000)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const d = dashboard as any

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Security</h1>
          <p className="text-gray-500 mt-1 text-sm">
            Vulnerability and license findings across all fleet nodes. Powered by Trivy, CxOne, and SonarQube.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => scanAllMutation.mutate('trivy')}
            disabled={scanAllMutation.isPending}
            className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 disabled:opacity-50 shadow-sm"
          >
            {scanAllMutation.isPending ? 'Scanning...' : 'Scan All (Trivy)'}
          </button>
          {integrations?.cxone.configured && (
            <button
              onClick={() => scanAllMutation.mutate('cxone')}
              disabled={scanAllMutation.isPending}
              className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 disabled:opacity-50"
            >
              Scan via CxOne
            </button>
          )}
        </div>
      </div>

      {/* Integration status */}
      <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center justify-between">
        <IntegrationBar status={integrations} />
        <a href="/settings" className="text-xs text-brand-600 hover:text-brand-700">Configure integrations</a>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Critical & High', value: (d?.vulnerabilities?.critical ?? 0) + (d?.vulnerabilities?.high ?? 0), color: 'text-red-600', bg: 'bg-red-50 border-red-200' },
          { label: 'Medium & Low', value: (d?.vulnerabilities?.medium ?? 0) + (d?.vulnerabilities?.low ?? 0), color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200' },
          { label: 'License Risks', value: (d?.license_risks?.high ?? 0) + (d?.license_risks?.medium ?? 0), color: 'text-purple-700', bg: 'bg-purple-50 border-purple-200' },
          { label: 'Nodes at Risk', value: d?.nodes_with_critical_or_high ?? 0, color: 'text-orange-700', bg: 'bg-orange-50 border-orange-200' },
        ].map(card => (
          <div key={card.label} className={`rounded-xl border p-5 ${card.bg}`}>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{card.label}</p>
            <p className={`text-3xl font-bold mt-1 ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* Node table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Node Security Status</h2>
          {d?.last_scan_at && (
            <span className="text-xs text-gray-400">
              Last scan: {new Date(d.last_scan_at).toLocaleString()}
            </span>
          )}
        </div>
        {nodesLoading ? (
          <div className="flex items-center justify-center h-24 text-gray-400">Loading...</div>
        ) : !nodes?.items.length ? (
          <div className="flex flex-col items-center justify-center h-24 text-gray-400 gap-2">
            <p className="text-sm">No nodes found. Bootstrap nodes first, then run a scan.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide bg-gray-50 border-b border-gray-100">
                <th className="px-4 py-3">Node</th>
                <th className="px-4 py-3">Risk</th>
                <th className="px-4 py-3 text-red-600">Critical</th>
                <th className="px-4 py-3 text-orange-600">High</th>
                <th className="px-4 py-3 text-amber-600">Medium</th>
                <th className="px-4 py-3 text-blue-600">Low</th>
                <th className="px-4 py-3 text-purple-600">Lic. Risks</th>
                <th className="px-4 py-3">Last Scanned</th>
                <th className="px-4 py-3 w-24"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {nodes.items.map(node => (
                <tr key={node.node_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setSelectedNodeId(node.node_id)}
                      className="text-left"
                    >
                      <p className="font-medium text-gray-900 hover:text-brand-600">
                        {node.hostname ?? node.minion_id}
                      </p>
                      <p className="text-xs text-gray-400">{node.minion_id}</p>
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <RiskBadge risk={node.risk_level} />
                  </td>
                  <td className="px-4 py-3 text-center font-mono text-sm font-semibold text-red-600">
                    {node.vulnerabilities.critical || '-'}
                  </td>
                  <td className="px-4 py-3 text-center font-mono text-sm font-semibold text-orange-600">
                    {node.vulnerabilities.high || '-'}
                  </td>
                  <td className="px-4 py-3 text-center font-mono text-sm text-amber-600">
                    {node.vulnerabilities.medium || '-'}
                  </td>
                  <td className="px-4 py-3 text-center font-mono text-sm text-blue-600">
                    {node.vulnerabilities.low || '-'}
                  </td>
                  <td className="px-4 py-3 text-center font-mono text-sm text-purple-600">
                    {(node.license_risks.high + node.license_risks.medium) || '-'}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {node.last_scanned_at
                      ? new Date(node.last_scanned_at).toLocaleDateString()
                      : <span className="text-gray-300">never</span>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex gap-1 justify-end">
                      <button
                        onClick={() => setSelectedNodeId(node.node_id)}
                        className="text-xs text-brand-600 hover:text-brand-700 font-medium px-2 py-1"
                      >
                        View
                      </button>
                      <button
                        onClick={() => scanNodeMutation.mutate({ nodeId: node.node_id, scanner: 'trivy' })}
                        disabled={!node.has_sbom || scanNodeMutation.isPending}
                        className="text-xs text-gray-500 hover:text-gray-700 font-medium px-2 py-1 disabled:opacity-30"
                        title={!node.has_sbom ? 'No SBOM available - bootstrap node first' : 'Scan with Trivy'}
                      >
                        Scan
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Active PAM Sessions */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Active SSH Sessions (PAM)</h2>
          <span className="text-xs text-gray-400">
            {activeSessions?.items.filter(s => s.status === 'active').length ?? 0} live
          </span>
        </div>
        {!activeSessions?.items.length ? (
          <div className="flex items-center justify-center h-16 text-gray-400 text-sm">
            No active sessions
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide bg-gray-50 border-b border-gray-100">
                <th className="px-4 py-3">Node ID</th>
                <th className="px-4 py-3">SSH User</th>
                <th className="px-4 py-3">Source IP</th>
                <th className="px-4 py-3">Credentials</th>
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-red-600">Alerts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {activeSessions.items.map(s => (
                <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2 font-mono text-xs text-gray-700">
                    {s.target_ip ?? s.node_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">{s.ssh_user ?? '—'}</td>
                  <td className="px-4 py-2 text-xs text-gray-500">{s.source_ip ?? '—'}</td>
                  <td className="px-4 py-2 text-xs text-gray-500">{s.credential_source}</td>
                  <td className="px-4 py-2 text-xs text-gray-400">
                    {new Date(s.started_at).toLocaleTimeString()}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${SESSION_STATUS_COLORS[s.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {s.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center">
                    {s.alert_count > 0 ? (
                      <span className="text-xs font-bold text-red-600">{s.alert_count}</span>
                    ) : (
                      <span className="text-xs text-gray-300">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent Security Events */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Security Event Feed</h2>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['security-events-recent'] })}
            className="text-xs text-brand-600 hover:text-brand-700"
          >
            Refresh
          </button>
        </div>
        {!recentEvents?.items.length ? (
          <div className="flex items-center justify-center h-16 text-gray-400 text-sm">
            No security events recorded
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {recentEvents.items.map(ev => (
              <div key={ev.id} className="px-4 py-2.5 flex items-start gap-3 hover:bg-gray-50">
                <span
                  className={`shrink-0 text-xs px-2 py-0.5 rounded border font-medium mt-0.5 ${
                    EVENT_SEVERITY_COLORS[ev.severity] ?? EVENT_SEVERITY_COLORS.info
                  }`}
                >
                  {ev.event_type}
                </span>
                <div className="flex-1 min-w-0">
                  {ev.command && (
                    <p className="text-xs font-mono text-gray-800 truncate">{ev.command}</p>
                  )}
                  {ev.detail && !ev.command && (
                    <p className="text-xs text-gray-500 truncate">{ev.detail}</p>
                  )}
                  {ev.node_id && (
                    <p className="text-xs text-gray-400 mt-0.5">{ev.node_id.slice(0, 8)}</p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-gray-400">
                  {new Date(ev.created_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {selectedNodeId && (
        <NodeSecurityDrawer nodeId={selectedNodeId} onClose={() => setSelectedNodeId(null)} />
      )}
    </div>
  )
}
