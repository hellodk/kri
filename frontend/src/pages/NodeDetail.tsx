import { Suspense, lazy, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { ansibleApi } from '../api/ansible'
import { iosTrackingApi } from '../api/iosTracking'
import { saltMastersApi, type SaltMaster } from '../api/saltMasters'
import { HealthBadge } from '../components/HealthBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { SshTabBar } from '../components/ssh/SshTabBar'
import { MultiSessionTerminal } from '../components/ssh/MultiSessionTerminal'
import type { SshTab } from '../components/ssh/SshTabBar'
import { VNCViewer } from '../components/VNCViewer'
import { formatDistanceToNow } from 'date-fns'
import { useToastStore } from '../stores/toastStore'
import { useAuthStore } from '../stores/authStore'
import { api } from '../api/client'
import { bootstrapRefetchInterval } from '../lib/bootstrapRefetchInterval'
import { isMacOSNode, type Tab } from './nodeDetail/utils'
import { OverviewTab } from './nodeDetail/OverviewTab'
import { DriftTab } from './nodeDetail/DriftTab'
import { SbomTab } from './nodeDetail/SbomTab'
import { ExecutionsTab } from './nodeDetail/ExecutionsTab'
import { BootstrapHistoryTab } from './nodeDetail/BootstrapHistoryTab'
import { SecretsTab } from './nodeDetail/SecretsTab'
import { ServicesTab } from './nodeDetail/ServicesTab'
import { ProcessesTab } from './nodeDetail/ProcessesTab'
import { ResourcesTab } from './nodeDetail/ResourcesTab'

// IOSTabPanel is only rendered for macOS/iOS hosts and pulls in heavier
// dependencies (date-fns differenceInDays/parseISO, ConfirmDialog, the iOS
// tracking API client). React.lazy keeps it out of the initial NodeDetail
// chunk; <Suspense> below provides a skeleton until the chunk loads
// (#arch-nodedetail).
const IOSTabPanel = lazy(() => import('./nodeDetail/IOSTabPanel'))

export function NodeDetail() {
  const { nodeId } = useParams<{ nodeId: string }>()
  const [tab, setTab] = useState<Tab>('overview')
  const [showRebootstrap, setShowRebootstrap] = useState(false)
  const [rebootstrapIp, setRebootstrapIp] = useState('')
  const [showSSH, setShowSSH] = useState(false)
  const [sshTabs, setSshTabs] = useState<SshTab[]>([])
  const [activeSshTabId, setActiveSshTabId] = useState<string>('')
  const [showVNC, setShowVNC] = useState(false)
  // iOS tab state
  const [showAddCert, setShowAddCert] = useState(false)
  const [showJenkinsConfigure, setShowJenkinsConfigure] = useState(false)
  const [jenkinsForm, setJenkinsForm] = useState({ jenkins_url: '', agent_name: '' })
  const [checkingJenkins, setCheckingJenkins] = useState(false)
  // AI Recommendations state — shared by Overview + Resources tabs
  const [aiLoading, setAiLoading] = useState(false)
  const [aiRecommendation, setAiRecommendation] = useState<string | null>(null)
  const [aiError, setAiError] = useState<string | null>(null)
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const currentUser = useAuthStore((s) => s.user)
  const isAdmin = currentUser?.role === 'admin'
  const canManage = currentUser?.role === 'admin' || currentUser?.role === 'operator'

  const { data: node, isLoading, isError, refetch } = useQuery({
    queryKey: ['node', nodeId],
    queryFn: () => fleetApi.node(nodeId!),
    staleTime: 60_000,
    enabled: !!nodeId,
    refetchInterval: (q) => bootstrapRefetchInterval(q.state.data?.bootstrap_status),
  })

  const { data: platformSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
    staleTime: 60_000,
  })
  const vncEnabled = platformSettings?.vnc_enabled ?? false

  // Fetch all salt-masters — lightweight, 60s stale — to find if this node runs one
  const { data: saltMasters } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
    staleTime: 60_000,
    enabled: !!nodeId,
  })
  // The salt-master record linked to this node (if any)
  const nodeMaster: SaltMaster | undefined = (saltMasters ?? []).find(
    (m) => m.node_id === nodeId,
  )

  const { data: iosDetail } = useQuery({
    queryKey: ['ios-node-detail', nodeId],
    queryFn: () => iosTrackingApi.getNode(nodeId!),
    staleTime: 60_000,
    enabled: !!nodeId && tab === 'ios' && !!node && isMacOSNode(node),
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

  const deleteCertMutation = useMutation({
    mutationFn: (certId: string) => iosTrackingApi.deleteCertificate(certId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ios-node-detail', nodeId] }); toast('Certificate deleted') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const upsertJenkinsMutation = useMutation({
    mutationFn: (body: { jenkins_url: string; agent_name: string }) =>
      iosTrackingApi.upsertJenkinsAgent(nodeId!, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ios-node-detail', nodeId] })
      setShowJenkinsConfigure(false)
      toast('Jenkins agent saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  // #560 — promote this node to salt-master
  const promoteMutation = useMutation({
    mutationFn: () => saltMastersApi.promoteFromNode(nodeId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      toast('Node promoted to salt-master. Go to Overview → Salt Masters to provision it.', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  async function checkJenkinsNow() {
    if (!nodeId) return
    setCheckingJenkins(true)
    try {
      await iosTrackingApi.checkJenkinsNow(nodeId)
      qc.invalidateQueries({ queryKey: ['ios-node-detail', nodeId] })
      toast('Jenkins status refreshed')
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Check failed', 'error')
    } finally {
      setCheckingJenkins(false)
    }
  }

  const askAI = useCallback(async () => {
    if (!nodeId) return
    setAiLoading(true)
    setAiRecommendation(null)
    setAiError(null)
    try {
      const resp = await api.post<{ recommendation: string; model_used: string }>(
        `/api/v1/nodes/${nodeId}/ask-ai`,
        {}
      )
      setAiRecommendation(resp.recommendation)
    } catch (e: unknown) {
      setAiError(e instanceof Error ? e.message : 'AI unavailable')
    } finally {
      setAiLoading(false)
    }
  }, [nodeId])

  if (isLoading) return <Skeleton rows={8} />
  if (isError || !node) return <ErrorState message="Node not found" retry={refetch} />

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'resources' as Tab, label: 'Resources' },
    { id: 'drift', label: 'Drift' },
    { id: 'sbom', label: 'SBOM' },
    { id: 'executions', label: 'Executions' },
    { id: 'bootstrap-history', label: 'Bootstrap History' },
    { id: 'secrets', label: 'Secrets' },
    { id: 'services' as Tab, label: 'Services' },
    { id: 'processes' as Tab, label: 'Processes' },
    ...(isMacOSNode(node) ? [{ id: 'ios' as Tab, label: 'iOS' }] : []),
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">
              {node.hostname ?? node.minion_id}
            </h1>
            <HealthBadge
              nodeId={node.id}
              health={node.health}
              status={node.status}
              sshState={node.ssh_state}
              sshCheckedAt={node.ssh_checked_at}
              sshDetail={node.ssh_detail}
              lastSeenAt={node.last_seen_at}
              maintenanceMode={node.maintenance_mode}
              canManage={canManage}
            />
            <DriftBadge score={node.drift_score} />
          </div>
          <p className="text-sm text-gray-500 mt-1">
            {node.ip_address ?? node.bootstrap_ip ?? 'IP unknown'} ·{' '}
            {node.last_seen_at
              ? `Last seen ${formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })}`
              : 'Never seen'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={askAI}
            disabled={aiLoading}
            title="Get AI recommendations for this node"
            className="px-3 py-2 text-sm font-medium rounded-lg border border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100 shadow-xs disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {aiLoading ? (
              <span className="w-3.5 h-3.5 border border-blue-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <span>🤖</span>
            )}
            <span className="hidden sm:inline">Ask AI</span>
          </button>
          <button
            onClick={() => maintenanceMutation.mutate(!node.maintenance_mode)}
            disabled={maintenanceMutation.isPending}
            className={`px-3 py-2 text-sm font-medium rounded-lg border shadow-xs disabled:opacity-50 transition-colors ${
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
            onClick={() => {
              setRebootstrapIp(node.bootstrap_ip ?? node.ip_address ?? '')
              setShowRebootstrap(true)
            }}
            className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-xs transition-colors"
            title="Run Ansible bootstrap playbook on this node"
          >
            ⊡ Bootstrap
          </button>
          <button
            onClick={() => {
              const firstTab: SshTab = {
                id: crypto.randomUUID(),
                nodeId: node.id,
                nodeName: node.hostname ?? node.minion_id,
                sessionId: null,
              }
              setSshTabs([firstTab])
              setActiveSshTabId(firstTab.id)
              setShowSSH(true)
            }}
            disabled={!node.bootstrap_ip}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 shadow-xs font-mono"
            title={!node.bootstrap_ip ? 'Bootstrap node first to get its IP' : `SSH into ${node.hostname} (${node.status})`}
          >
            SSH
          </button>
          {vncEnabled && (
            <button
              onClick={() => setShowVNC(true)}
              disabled={!node.bootstrap_ip}
              className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 disabled:opacity-40 shadow-xs font-mono"
              title={!node.bootstrap_ip ? 'Bootstrap node first to get its IP' : `VNC into ${node.hostname} (${node.status})`}
            >
              VNC
            </button>
          )}
          {/* #560 — Promote to salt-master (admin only; hidden when already a master) */}
          {isAdmin && !nodeMaster && (
            <button
              onClick={() => promoteMutation.mutate()}
              disabled={promoteMutation.isPending || !node.bootstrap_ip}
              title={
                !node.bootstrap_ip
                  ? 'Bootstrap the node first to obtain a reachable IP'
                  : 'Promote this node to also act as a salt-master'
              }
              className="px-3 py-2 text-sm font-medium rounded-lg border border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-40 shadow-xs transition-colors"
            >
              {promoteMutation.isPending ? 'Promoting…' : '⬆ Promote to Master'}
            </button>
          )}
          <Link to="/fleet" className="text-sm text-brand-600 hover:underline">← Fleet</Link>
        </div>
      </div>

      <div
        role="tablist"
        aria-label="Node detail sections"
        onKeyDown={(e) => {
          const idx = tabs.findIndex((t) => t.id === tab)
          let next: number
          if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length
          else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length
          else if (e.key === 'Home') next = 0
          else if (e.key === 'End') next = tabs.length - 1
          else return
          e.preventDefault()
          const nextId = tabs[next].id
          setTab(nextId)
          requestAnimationFrame(() => document.getElementById(`tab-${nextId}`)?.focus())
        }}
        className="sticky top-0 z-20 bg-white border-b border-gray-200 flex gap-1 -mx-6 px-6"
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`tabpanel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-gray-600 hover:text-gray-800'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab
          node={node}
          nodeId={nodeId!}
          nodeMaster={nodeMaster}
          canManage={canManage}
          showRebootstrap={showRebootstrap}
          setShowRebootstrap={setShowRebootstrap}
          rebootstrapIp={rebootstrapIp}
          setRebootstrapIp={setRebootstrapIp}
          aiLoading={aiLoading}
          aiRecommendation={aiRecommendation}
          aiError={aiError}
          onAskAI={askAI}
          refetchNode={refetch}
        />
      )}

      {tab === 'drift' && <DriftTab nodeId={nodeId!} />}

      {tab === 'sbom' && <SbomTab nodeId={nodeId!} />}

      {tab === 'executions' && <ExecutionsTab nodeId={nodeId!} />}

      {showSSH && sshTabs.length > 0 && (
        <div className="fixed inset-0 z-50 flex flex-col bg-gray-950">
          {/* Modal header */}
          <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-mono text-gray-300">
                SSH &rarr; <span className="text-cyan-400">{node.hostname ?? node.minion_id}</span>
              </span>
              <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                {sshTabs.length} {sshTabs.length === 1 ? 'session' : 'sessions'}
              </span>
              <span className="text-xs text-amber-500 bg-gray-800 px-2 py-0.5 rounded">
                Sessions recorded
              </span>
            </div>
            <button
              onClick={() => {
                setShowSSH(false)
                setSshTabs([])
                setActiveSshTabId('')
              }}
              className="text-gray-400 hover:text-white text-lg px-3 py-1 hover:bg-gray-800 rounded transition-colors"
            >
              × Close All
            </button>
          </div>

          {/* Tab bar */}
          <SshTabBar
            tabs={sshTabs}
            activeTabId={activeSshTabId}
            onTabSelect={setActiveSshTabId}
            onTabClose={(tabId) => {
              const remaining = sshTabs.filter((t) => t.id !== tabId)
              if (remaining.length === 0) {
                setShowSSH(false)
                setSshTabs([])
                setActiveSshTabId('')
              } else {
                setSshTabs(remaining)
                // If we closed the active tab, switch to last remaining tab
                if (tabId === activeSshTabId) {
                  setActiveSshTabId(remaining[remaining.length - 1].id)
                }
              }
            }}
            onNewTab={() => {
              const newTab: SshTab = {
                id: crypto.randomUUID(),
                nodeId: node.id,
                nodeName: node.hostname ?? node.minion_id,
                sessionId: null,
              }
              setSshTabs((prev) => [...prev, newTab])
              setActiveSshTabId(newTab.id)
            }}
          />

          {/* Terminal area — fills remaining height */}
          <MultiSessionTerminal
            tabs={sshTabs}
            activeTabId={activeSshTabId}
            onCredentialError={() => {
              setShowSSH(false)
              setTab('secrets')
            }}
          />
        </div>
      )}

      {showVNC && (
        <VNCViewer
          nodeId={node.id}
          nodeName={node.hostname ?? node.minion_id}
          onClose={() => setShowVNC(false)}
        />
      )}

      {tab === 'secrets' && <SecretsTab node={node} nodeId={nodeId!} />}

      {tab === 'ios' && isMacOSNode(node) && (
        <div role="tabpanel" id="tabpanel-ios" aria-labelledby="tab-ios">
        <Suspense fallback={<Skeleton rows={6} />}>
          <IOSTabPanel
            node={node}
            nodeId={nodeId!}
            iosDetail={iosDetail ?? null}
            showAddCert={showAddCert}
            setShowAddCert={setShowAddCert}
            showJenkinsConfigure={showJenkinsConfigure}
            setShowJenkinsConfigure={setShowJenkinsConfigure}
            jenkinsForm={jenkinsForm}
            setJenkinsForm={setJenkinsForm}
            checkingJenkins={checkingJenkins}
            checkJenkinsNow={checkJenkinsNow}
            deleteCertMutation={deleteCertMutation}
            upsertJenkinsMutation={upsertJenkinsMutation}
            qc={qc}
            toast={toast}
          />
        </Suspense>
        </div>
      )}

      {tab === 'bootstrap-history' && <BootstrapHistoryTab nodeId={nodeId!} />}

      {tab === 'services' && <ServicesTab node={node} nodeId={nodeId!} />}

      {tab === 'processes' && <ProcessesTab node={node} nodeId={nodeId!} />}

      {tab === 'resources' && (
        <ResourcesTab
          nodeId={nodeId!}
          aiLoading={aiLoading}
          aiRecommendation={aiRecommendation}
          aiError={aiError}
          onAskAI={askAI}
        />
      )}
    </div>
  )
}
