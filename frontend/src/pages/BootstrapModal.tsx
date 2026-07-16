import { useEffect, useRef, useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ansibleApi } from '../api/ansible'
import { searchApi } from '../api/search'
import { fleetApi } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { saltMastersApi } from '../api/saltMasters'
import { canBootstrap, saltMasterBadge } from '../lib/saltMasterHelpers'
import { AnsiText } from '../lib/AnsiText'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useJobEventStream } from '../hooks/useJobEventStream'
import { useToastStore } from '../stores/toastStore'
import type { Node } from '../types'


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
  const [subMode, setSubMode] = useState<'existing' | 'new'>('existing')

  // Shared state for both sub-modes
  const [minionId, setMinionId] = useState('')
  const [targetIp, setTargetIp] = useState('')
  const [sshUsername, setSshUsername] = useState('')
  const [sshPassword, setSshPassword] = useState('')
  const [showSshPassword, setShowSshPassword] = useState(false)
  const [nodeId, setNodeId] = useState<string | null>(null)
  const [showPlaybook, setShowPlaybook] = useState(false)
  const [existingNodeDbId, setExistingNodeDbId] = useState<string | null>(null)

  // Advanced options (#830)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [neVersion, setNeVersion] = useState('1.8.2')
  const [neListenAddress, setNeListenAddress] = useState(':9100')
  const [neUrlOverride, setNeUrlOverride] = useState('')
  const [asMaster, setAsMaster] = useState(false)

  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()
  const navigate = useNavigate()

  // Existing node picker state
  const [nodeSearch, setNodeSearch] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedNodeHasSavedPassword, setSelectedNodeHasSavedPassword] = useState(false)

  // Load SSH credential defaults from platform settings
  const { data: settingsData } = useQuery({
    queryKey: ['platform-settings'],
    queryFn: () => ansibleApi.getSettings(),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (settingsData) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- pre-populating SSH username from saved settings on mount; refactor tracked in #380 follow-up
      if (!sshUsername) setSshUsername(settingsData.ssh_bootstrap_username || '')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsData])

  // All nodes for the picker
  const { data: allNodes } = useQuery({
    queryKey: ['all-nodes-for-bootstrap'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    staleTime: 30_000,
    enabled: subMode === 'existing',
  })

  const filtered = (allNodes?.items ?? []).filter((n) =>
    !nodeSearch ||
    n.minion_id.toLowerCase().includes(nodeSearch.toLowerCase()) ||
    (n.hostname ?? '').toLowerCase().includes(nodeSearch.toLowerCase())
  )

  // "New node" sub-mode: look up by typed minion ID (existing behaviour)
  const { data: searchData } = useQuery({
    queryKey: ['bootstrap-lookup', minionId],
    queryFn: () => searchApi.search(minionId),
    enabled: subMode === 'new' && minionId.length >= 3,
    staleTime: 10_000,
  })

  const exactMatch = subMode === 'new'
    ? (searchData?.items?.find(
        (r) => r.minion_id === minionId ||
               r.minion_id.split('.')[0] === minionId ||
               r.hostname === minionId
      ) ?? null)
    : null

  // Fetch full node details: for "new" mode via search, for "existing" mode via selected node
  const detailNodeId = subMode === 'existing' ? selectedNodeId : (exactMatch?.id ?? null)

  const { data: existingNode } = useQuery({
    queryKey: ['node', detailNodeId],
    queryFn: () => fleetApi.node(detailNodeId!),
    enabled: !!detailNodeId,
    staleTime: 30_000,
  })

  // Auto-populate from found node (new mode search result)
  useEffect(() => {
    if (subMode === 'new' && existingNode) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing node fields from search result on prop change; refactor tracked in #380 follow-up
      setExistingNodeDbId(existingNode.id)
      if (existingNode.ip_address) setTargetIp(existingNode.ip_address)
      if (existingNode.ssh_username) setSshUsername(existingNode.ssh_username)
    } else if (subMode === 'new') {
      setExistingNodeDbId(null)
    }
  }, [existingNode, subMode])

  // Select an existing node from the picker
  function selectExistingNode(n: Node) {
    setSelectedNodeId(n.id)
    setExistingNodeDbId(n.id)
    setMinionId(n.minion_id)
    setTargetIp(n.ip_address ?? '')
    // Will be refined once detail loads; use Node-level hint if available
    if (n.ssh_username) setSshUsername(n.ssh_username)
    setSelectedNodeHasSavedPassword(n.has_ssh_password ?? false)
  }

  // Refine after detail loads (existing mode)
  useEffect(() => {
    if (subMode === 'existing' && existingNode && selectedNodeId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- populating form fields from loaded node detail; refactor tracked in #380 follow-up
      setTargetIp(existingNode.ip_address ?? targetIp)
      if (existingNode.ssh_username) setSshUsername(existingNode.ssh_username)
      setSelectedNodeHasSavedPassword(existingNode.has_ssh_password)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingNode, subMode, selectedNodeId])

  const { data: playbookData } = useQuery({
    queryKey: ['playbook-content', 'bootstrap_node.yml'],
    queryFn: () => ansibleApi.playbookContent('bootstrap_node.yml'),
    enabled: showPlaybook,
    staleTime: Infinity,
  })

  const [localLogs, setLocalLogs] = useState<string | null>(null)

  const bootstrapMutation = useMutation({
    mutationFn: () => ansibleApi.bootstrap(
      minionId,
      targetIp,
      sshUsername || undefined,
      sshPassword || undefined,
      selectedMasterIds.size > 0 ? Array.from(selectedMasterIds) : undefined,
      {
        nodeExporterVersion: neVersion !== '1.8.2' ? neVersion : undefined,
        nodeExporterListenAddress: neListenAddress !== ':9100' ? neListenAddress : undefined,
        nodeExporterUrlOverride: neUrlOverride || undefined,
        asMaster,
      },
    ),
    onMutate: () => { setLocalLogs('') },
    onSuccess: (data) => { setNodeId(data.node_id); setShowLogs(true); toast('Bootstrap started') },
    onError: (e: Error) => { setLocalLogs(null); toast(e.message, 'error') },
  })

  // Live push: refetch bootstrap status/logs on server-pushed transitions
  // (#756). Polling below drops to a slow 30s safety-net.
  useJobEventStream({ enabled: !!nodeId })

  const { data: statusData } = useQuery({
    queryKey: ['bootstrap-status', nodeId],
    queryFn: () => ansibleApi.bootstrapStatus(nodeId!),
    enabled: !!nodeId,
    refetchInterval: (query) => {
      const s = query.state.data?.bootstrap_status
      return (s === 'pending' || s === 'bootstrapping') ? 30_000 : false
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
  const [copiedLogs, setCopiedLogs] = useState(false)

  const { data: logsData } = useQuery({
    queryKey: ['bootstrap-logs', nodeId],
    queryFn: () => ansibleApi.bootstrapLogs(nodeId!),
    enabled: showLogs && !!nodeId,
    refetchInterval: showLogs && (status === 'pending' || status === 'bootstrapping') ? 30_000 : false,
  })

  // Keep localLogs in sync: once the query returns real data, promote it so clearing works
  useEffect(() => {
    if (logsData?.ansible_stdout !== undefined) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing local log buffer from query data so user can clear logs independently; refactor tracked in #380 follow-up
      setLocalLogs(logsData.ansible_stdout)
    }
  }, [logsData?.ansible_stdout])

  // Cancel mutation for stuck bootstraps — declared before any early returns (Rules of Hooks)
  const cancelMutation = useMutation({
    mutationFn: () => ansibleApi.cancelBootstrap(existingNodeDbId!),
    onSuccess: () => {
      toast('Bootstrap cancelled — you can now re-bootstrap')
      setExistingNodeDbId(null)
      qc.invalidateQueries({ queryKey: ['node', existingNode?.id] })
      qc.invalidateQueries({ queryKey: ['bootstrap-lookup', minionId] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  // Auto-scroll log panel to bottom when new content arrives
  const preRef = useRef<HTMLPreElement>(null)
  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight
    }
  }, [localLogs])

  // Multi-master selection (#534) — fetch all enabled masters, pre-check all of them.
  // Health is a WARNING (badge only), not a gate — canBootstrap requires ≥1 selected.
  const { data: saltMasters } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
    staleTime: 30_000,
  })
  const enabledMasters = (saltMasters ?? []).filter((m) => m.enabled)
  const [selectedMasterIds, setSelectedMasterIds] = useState<Set<string>>(new Set())

  // Pre-select all enabled masters whenever the list first loads
  useEffect(() => {
    if (enabledMasters.length > 0 && selectedMasterIds.size === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- initialising master selection from loaded list; single-direction sync
      setSelectedMasterIds(new Set(enabledMasters.map((m) => m.id)))
    }
  }, [saltMasters]) // eslint-disable-line react-hooks/exhaustive-deps

  // Detect stuck bootstrap — only if bootstrap_status is returned by backend
  const isStuckBootstrap = !nodeId &&
    !!existingNode &&
    !!existingNodeDbId &&
    (existingNode.bootstrap_status === 'bootstrapping' || existingNode.bootstrap_status === 'pending')

  // If node is already bootstrapping/pending, show live status + cancel instead of form
  if (isStuckBootstrap) {
    return (
      <div className="space-y-4">
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl space-y-1">
          <p className="text-sm font-semibold text-amber-800">Bootstrap already in progress</p>
          <p className="text-xs text-amber-700">
            <span className="font-mono">{existingNode.minion_id}</span> is currently being bootstrapped.
            If this has been stuck for more than a few minutes, cancel it and retry.
          </p>
        </div>

        <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
          <div className={`text-sm font-semibold ${
            existingNode.bootstrap_status === 'bootstrapping' ? 'text-brand-600' : 'text-gray-500'
          }`}>
            {existingNode.bootstrap_status === 'bootstrapping' ? 'Running…' : 'Queued'}
          </div>
          <div className="text-sm text-gray-600 flex-1">
            {existingNode.hostname ?? existingNode.minion_id}
            {existingNode.bootstrap_ip ? ` @ ${existingNode.bootstrap_ip}` : ''}
          </div>
          <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
        </div>

        {existingNode.bootstrap_error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-mono">
            {existingNode.bootstrap_error}
          </div>
        )}

        <div className="flex gap-3">
          <button onClick={onClose}
            className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Close (runs in background)
          </button>
          <button
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
            className="flex-1 py-2.5 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50">
            {cancelMutation.isPending ? 'Cancelling…' : 'Cancel bootstrap'}
          </button>
        </div>
      </div>
    )
  }

  if (!nodeId) {
    const hasSavedPassword = subMode === 'existing'
      ? selectedNodeHasSavedPassword
      : (existingNode?.has_ssh_password ?? false)

    const canSubmit = !!minionId && !!targetIp && !!sshUsername &&
      (!(!sshPassword && !hasSavedPassword)) &&
      !bootstrapMutation.isPending &&
      canBootstrap(selectedMasterIds.size)

    return (
      <form onSubmit={(e) => { e.preventDefault(); bootstrapMutation.mutate() }} className="space-y-4">

        {/* Sub-mode pill tabs */}
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {(['existing', 'new'] as const).map((m) => (
            <button key={m} type="button" onClick={() => {
              setSubMode(m)
              // Reset selection when switching modes
              setMinionId('')
              setTargetIp('')
              setSelectedNodeId(null)
              setExistingNodeDbId(null)
              setSshPassword('')
              setSelectedNodeHasSavedPassword(false)
              if (settingsData) setSshUsername(settingsData.ssh_bootstrap_username || '')
            }}
              className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                subMode === m ? 'bg-white text-gray-900 shadow-xs' : 'text-gray-500 hover:text-gray-700'
              }`}>
              {m === 'existing' ? 'Existing node' : 'New node'}
            </button>
          ))}
        </div>

        {subMode === 'existing' ? (
          /* ── Existing node picker ── */
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Select node</label>
              <input
                placeholder="Search nodes…"
                value={nodeSearch}
                onChange={(e) => setNodeSearch(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600 mb-2"
              />
              <div className="border border-gray-200 rounded-lg max-h-48 overflow-y-auto">
                {filtered.map((n) => (
                  <button key={n.id} type="button"
                    onClick={() => selectExistingNode(n)}
                    className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center justify-between border-b border-gray-100 last:border-0 ${
                      selectedNodeId === n.id ? 'bg-brand-50 text-brand-700' : 'text-gray-900'
                    }`}>
                    <span className="font-medium">{n.hostname ?? n.minion_id}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      n.status === 'online' ? 'bg-green-100 text-green-700' :
                      n.status === 'offline' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-500'
                    }`}>{n.status}</span>
                  </button>
                ))}
                {filtered.length === 0 && !allNodes && (
                  <p className="px-3 py-4 text-sm text-gray-400 text-center">Loading nodes…</p>
                )}
                {filtered.length === 0 && allNodes && (
                  <p className="px-3 py-4 text-sm text-gray-400 text-center">No nodes found</p>
                )}
              </div>
            </div>

            {selectedNodeId && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    IP address <span className="ml-1 text-xs font-normal text-gray-400">(locked — from node record)</span>
                  </label>
                  <input
                    value={targetIp}
                    readOnly
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-500 bg-gray-50 cursor-not-allowed focus:outline-hidden"
                  />
                </div>

                {/* SSH Credentials */}
                <div className="border-t border-gray-100 pt-3 space-y-3">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">SSH Credentials</p>
                  <p className="text-xs text-gray-400">
                    Credentials auto-resolved from node → group → global settings. Enter here to override for this run only.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                      <input
                        value={sshUsername}
                        onChange={(e) => setSshUsername(e.target.value)}
                        placeholder="admin"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                      {selectedNodeHasSavedPassword && !sshPassword ? (
                        <div className="w-full px-3 py-2 border border-green-200 rounded-lg text-sm bg-green-50 text-green-700 flex items-center gap-1.5">
                          <span>✓</span>
                          <span>Using saved password</span>
                        </div>
                      ) : (
                        <div className="relative">
                          <input
                            type={showSshPassword ? 'text' : 'password'}
                            value={sshPassword}
                            onChange={(e) => setSshPassword(e.target.value)}
                            placeholder={selectedNodeHasSavedPassword ? 'Override saved password' : '••••••••'}
                            className="w-full px-3 py-2 pr-9 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                          />
                          <button type="button" onClick={() => setShowSshPassword(!showSshPassword)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                            {showSshPassword ? '🙈' : '👁'}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        ) : (
          /* ── New node form (original behaviour) ── */
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Minion ID <span className="text-gray-400 font-normal">(e.g. mac-mini-01)</span>
              </label>
              <input required value={minionId} onChange={(e) => {
                  setMinionId(e.target.value)
                  if (!existingNodeDbId) setTargetIp('')
                }}
                placeholder="mac-mini-01"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600" />
              {existingNode && (
                <p className="text-xs text-brand-600 mt-1 flex items-center gap-1">
                  <span>✓</span> Node found in fleet — IP pre-filled and locked
                </p>
              )}
              {minionId.length >= 3 && !existingNode && searchData && (
                <p className="text-xs text-gray-400 mt-1">New node — enter IP address below</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                IP address
                {existingNodeDbId && (
                  <span className="ml-2 text-xs font-normal text-gray-400">(locked — node already registered)</span>
                )}
              </label>
              <input required value={targetIp}
                readOnly={!!existingNodeDbId}
                onChange={(e) => !existingNodeDbId && setTargetIp(e.target.value)}
                placeholder="10.0.1.11"
                className={`w-full px-3 py-2 border rounded-lg text-sm text-gray-900 focus:outline-hidden ${
                  existingNodeDbId
                    ? 'bg-gray-50 border-gray-200 text-gray-500 cursor-not-allowed'
                    : 'border-gray-300 focus:border-brand-600'
                }`} />
            </div>
            {/* SSH Credentials */}
            <div className="border-t border-gray-100 pt-4 space-y-3">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">SSH Credentials</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                  <input
                    value={sshUsername}
                    onChange={(e) => setSshUsername(e.target.value)}
                    placeholder="admin"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                  <div className="relative">
                    <input
                      type={showSshPassword ? 'text' : 'password'}
                      value={sshPassword}
                      onChange={(e) => setSshPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-3 py-2 pr-9 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                    />
                    <button type="button" onClick={() => setShowSshPassword(!showSshPassword)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      {showSshPassword ? '🙈' : '👁'}
                    </button>
                  </div>
                </div>
              </div>
              {existingNode?.has_ssh_password && !sshPassword && (
                <p className="text-xs text-brand-600">Saved password will be used — enter a new one to override.</p>
              )}
              {!existingNode?.has_ssh_password && (
                <p className="text-xs text-gray-400">Overrides global Settings credentials for this run only.</p>
              )}
            </div>
          </div>
        )}

        {/* Advanced options (#830) */}
        <div className="border border-gray-200 rounded-xl overflow-hidden">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors"
            aria-expanded={showAdvanced}
          >
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              Advanced — node_exporter &amp; minion options
            </span>
            <span className="text-gray-400 text-xs">{showAdvanced ? '▲' : '▼'}</span>
          </button>
          {showAdvanced && (
            <div className="px-3 py-3 space-y-3 border-t border-gray-100">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    node_exporter version
                  </label>
                  <input
                    value={neVersion}
                    onChange={(e) => setNeVersion(e.target.value)}
                    placeholder="1.8.2"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Listen address
                  </label>
                  <input
                    value={neListenAddress}
                    onChange={(e) => setNeListenAddress(e.target.value)}
                    placeholder=":9100"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  node_exporter download URL override
                </label>
                <input
                  value={neUrlOverride}
                  onChange={(e) => setNeUrlOverride(e.target.value)}
                  placeholder="leave blank for default"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600"
                />
              </div>
            </div>
          )}
        </div>

        {/* Playbook preview */}
        <div>
          <button
            type="button"
            onClick={() => setShowPlaybook(!showPlaybook)}
            className="text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
          >
            {showPlaybook ? '▲ Hide playbook' : '▼ Preview bootstrap playbook'}
          </button>
          {showPlaybook && (
            <div className="mt-2 rounded-xl border border-gray-200 overflow-hidden">
              <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 flex items-center justify-between">
                <span className="text-xs font-mono text-gray-600">bootstrap_node.yml</span>
                <span className="text-xs text-gray-400">read-only preview</span>
              </div>
              <pre className="text-xs font-mono bg-gray-900 text-gray-100 p-3 overflow-auto max-h-80 whitespace-pre">
                {playbookData?.content ?? 'Loading…'}
              </pre>
            </div>
          )}
        </div>

        {/* Salt Masters multi-select (#534) ─ health is a warning badge, not a gate */}
        <div className="border border-gray-200 rounded-xl overflow-hidden">
          <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Salt Masters</span>
            <div className="flex gap-2">
              <button type="button"
                onClick={() => setSelectedMasterIds(new Set(enabledMasters.map((m) => m.id)))}
                className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                All
              </button>
              <button type="button"
                onClick={() => setSelectedMasterIds(new Set())}
                className="text-xs text-gray-500 hover:text-gray-700 font-medium">
                None
              </button>
            </div>
          </div>
          {saltMasters === undefined ? (
            <p className="px-3 py-4 text-sm text-gray-400 text-center">Loading masters…</p>
          ) : enabledMasters.length === 0 ? (
            <p className="px-3 py-4 text-sm text-red-600 text-center">
              No salt-master configured —{' '}
              <a href="/overview?tab=salt-masters" className="underline text-red-700 hover:text-red-800">
                add one in Overview → Salt Masters
              </a>
            </p>
          ) : (
            <div className="divide-y divide-gray-100">
              {enabledMasters.map((m) => {
                const badge = saltMasterBadge(m.status)
                const checked = selectedMasterIds.has(m.id)
                return (
                  <label key={m.id}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        const next = new Set(selectedMasterIds)
                        if (e.target.checked) { next.add(m.id) } else { next.delete(m.id) }
                        setSelectedMasterIds(next)
                      }}
                      className="rounded"
                    />
                    <span className="flex-1 text-sm font-medium text-gray-900">{m.name}</span>
                    <span className="text-xs text-gray-400 font-mono">{m.address}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${badge.bgClass} ${badge.textClass}`}>
                      {badge.label}
                    </span>
                  </label>
                )
              })}
            </div>
          )}
          {enabledMasters.length > 0 && selectedMasterIds.size === 0 && (
            <p className="px-3 py-2 text-xs text-red-600 bg-red-50 border-t border-red-100">
              Select at least one master to bootstrap.
            </p>
          )}
          {enabledMasters.length > 0 && selectedMasterIds.size > 0 &&
            Array.from(selectedMasterIds).some((id) => {
              const m = enabledMasters.find((x) => x.id === id)
              return m?.status === 'unreachable'
            }) && (
            <p className="px-3 py-2 text-xs text-amber-700 bg-amber-50 border-t border-amber-100">
              Warning: one or more selected masters are unreachable. Bootstrap will proceed — the minion will failover to reachable masters.
            </p>
          )}
        </div>

        {/* Master-first bootstrap (#1019) */}
        <div className="border border-gray-200 rounded-xl px-3 py-2">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={asMaster}
              onChange={(e) => setAsMaster(e.target.checked)}
              className="rounded"
            />
            <span className="text-sm font-medium text-gray-900">Also make this node a salt-master</span>
          </label>
          <p className="mt-1 pl-7 text-xs text-gray-500">
            Installs salt-master + salt-api on this node first, then enrols it.
          </p>
        </div>

        <p className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-lg p-3">
          Make sure Remote Login (SSH) is enabled before bootstrapping.
        </p>
        <div className="flex gap-3 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            title={enabledMasters.length === 0 ? 'Configure a salt-master first in Overview → Salt Masters' : undefined}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
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
      {status === 'bootstrapping' && (localLogs ?? logsData?.ansible_stdout) && (() => {
        const lastTask = (localLogs ?? logsData?.ansible_stdout ?? '')
          .split('\n')
          .filter((l) => /^TASK \[/.test(l))
          .pop()
        const taskName = lastTask ? lastTask.replace(/^TASK \[/, '').replace(/\].*$/, '') : null
        return taskName ? (
          <p className="text-xs text-gray-500 -mt-2">Currently: <span className="font-mono">{taskName}</span></p>
        ) : null
      })()}
      {statusData?.bootstrap_error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-mono">
          {statusData.bootstrap_error}
        </div>
      )}
      {status === 'completed' && (
        <div className="space-y-2">
          <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
            Bootstrap complete. The Salt minion is starting — the node will appear in the fleet within 30–60 seconds.
          </p>
          <button
            onClick={() => { onClose(); navigate('/fleet') }}
            className="w-full py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
          >
            Go to Fleet Dashboard →
          </button>
        </div>
      )}

      {/* Log viewer */}
      {nodeId && (
        <button
          onClick={() => setShowLogs(!showLogs)}
          className="w-full py-2 border border-gray-200 text-gray-600 rounded-lg text-xs font-medium hover:bg-gray-50 flex items-center justify-center gap-1"
        >
          {showLogs ? '▲ Hide logs' : '▼ View logs (Salt pillar + Ansible output)'}
        </button>
      )}

      {showLogs && logsData && (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          {/* Ansible output header */}
          <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50">
            <div className="px-4 py-2 text-xs font-medium border-b-2 border-brand-600 text-brand-700 bg-white">
              <span className="flex items-center gap-1.5">
                Ansible output
                {(status === 'pending' || status === 'bootstrapping') && (
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                  </span>
                )}
              </span>
            </div>
            {(localLogs ?? logsData.ansible_stdout) && (
              <button
                type="button"
                title="Copy full Ansible output"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(localLogs ?? logsData.ansible_stdout ?? '')
                    setCopiedLogs(true)
                    setTimeout(() => setCopiedLogs(false), 1500)
                  } catch { /* clipboard unavailable */ }
                }}
                className="mr-3 inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-gray-600 border border-gray-300 rounded-md hover:bg-gray-100"
              >
                {copiedLogs ? <><Check size={14} className="text-emerald-600" />Copied</> : <><Copy size={14} />Copy</>}
              </button>
            )}
          </div>
          {/* Content */}
          <pre
            ref={preRef}
            className="text-xs font-mono bg-gray-900 p-3 overflow-auto max-h-[42rem] whitespace-pre-wrap"
          >
            {(localLogs ?? logsData.ansible_stdout) ? (
              <AnsiText raw={localLogs ?? logsData.ansible_stdout ?? ''} />
            ) : (
              <span className="text-gray-500">(no output captured yet — run in progress or not started)</span>
            )}
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
      return (s === 'pending' || s === 'bootstrapping') ? 30_000 : false
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
  const [bulkSubMode, setBulkSubMode] = useState<'csv' | 'group'>('group')
  const [input, setInput] = useState('')
  const [jobs, setJobs] = useState<BulkJob[]>([])
  const [launching, setLaunching] = useState(false)
  const [asMaster, setAsMaster] = useState(false)
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  // Live push: bulk rows refetch bootstrap status on server-pushed transitions
  // (#756); per-row polling drops to a slow 30s safety-net.
  useJobEventStream({ enabled: jobs.length > 0 })

  // Group mode state
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())

  const { data: groups } = useQuery({
    queryKey: ['groups-bootstrap'],
    queryFn: () => groupsApi.list({ per_page: 100 }),
    staleTime: 30_000,
    enabled: bulkSubMode === 'group',
  })

  const { data: groupMembersPage } = useQuery({
    queryKey: ['group-members-bootstrap', selectedGroupId],
    queryFn: () => groupsApi.members(selectedGroupId, { per_page: 200 }),
    enabled: !!selectedGroupId,
    staleTime: 10_000,
  })
  const groupMembers = groupMembersPage?.items ?? []

  // Pre-check unbootstrapped or failed nodes when group members load
  useEffect(() => {
    if (groupMembersPage) {
      const toPrecheck = groupMembers
        .filter((n) => {
          const bs = (n as Node & { bootstrap_status?: string }).bootstrap_status
          return !bs || bs === 'failed' || bs === 'unknown' || bs === 'unregistered'
        })
        .map((n) => n.id)
      // eslint-disable-next-line react-hooks/set-state-in-effect -- auto-checking eligible nodes when group page loads; refactor tracked in #380 follow-up
      setCheckedIds(new Set(toPrecheck))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupMembersPage])

  // CSV parse
  const parsedRows = input
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))
    .map((l) => {
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

  async function launchFromCsv() {
    if (parsedRows.length === 0) return
    setLaunching(true)
    const initial: BulkJob[] = parsedRows.map((r) => ({ ...r, extraTags: r.extraTags, nodeId: null, error: null }))
    setJobs(initial)

    const results = await Promise.allSettled(
      parsedRows.map((r) => ansibleApi.bootstrap(r.minionId, r.targetIp, undefined, undefined, undefined, { asMaster }))
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
    qc.invalidateQueries({ queryKey: ['nodes'] })
  }

  async function launchFromGroup() {
    const checked = groupMembers.filter((n) => checkedIds.has(n.id))
    if (checked.length === 0) return
    setLaunching(true)
    const initial: BulkJob[] = checked.map((n) => ({
      minionId: n.minion_id,
      targetIp: n.ip_address ?? '',
      extraTags: {},
      nodeId: null,
      error: null,
    }))
    setJobs(initial)

    const results = await Promise.allSettled(
      checked.map((n) => ansibleApi.bootstrap(n.minion_id, n.ip_address ?? '', undefined, undefined, undefined, { asMaster }))
    )

    setJobs(checked.map((n, i) => {
      const res = results[i]
      return {
        minionId: n.minion_id,
        targetIp: n.ip_address ?? '',
        extraTags: {},
        nodeId: res.status === 'fulfilled' ? res.value.node_id : null,
        error: res.status === 'rejected' ? String(res.reason) : null,
      }
    }))
    setLaunching(false)
    toast(`Launched ${checked.length} bootstrap job(s)`)
    qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    qc.invalidateQueries({ queryKey: ['nodes'] })
  }

  if (jobs.length > 0) {
    return (
      <div className="space-y-4">
        <div className="bg-gray-50 rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th scope="col" className="px-3 py-2 text-left">Minion ID</th>
                <th scope="col" className="px-3 py-2 text-left">IP</th>
                <th scope="col" className="px-3 py-2 text-left">Status</th>
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

  return (
    <div className="space-y-4">
      {/* Bulk sub-mode tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
        {(['group', 'csv'] as const).map((m) => (
          <button key={m} type="button" onClick={() => setBulkSubMode(m)}
            className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
              bulkSubMode === m ? 'bg-white text-gray-900 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {m === 'group' ? 'From Group' : 'CSV paste'}
          </button>
        ))}
      </div>

      {/* Master-first bootstrap (#1019) — applies to every job in this batch */}
      <div className="border border-gray-200 rounded-xl px-3 py-2">
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={asMaster}
            onChange={(e) => setAsMaster(e.target.checked)}
            className="rounded"
          />
          <span className="text-sm font-medium text-gray-900">Also make these nodes salt-masters</span>
        </label>
        <p className="mt-1 pl-7 text-xs text-gray-500">
          Installs salt-master + salt-api on each node first, then enrols it.
        </p>
      </div>

      {bulkSubMode === 'group' ? (
        /* ── Group mode ── */
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Select group</label>
            <select
              value={selectedGroupId}
              onChange={(e) => { setSelectedGroupId(e.target.value); setCheckedIds(new Set()) }}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600 bg-white"
            >
              <option value="">— choose a group —</option>
              {(groups?.items ?? []).map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </div>

          {selectedGroupId && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">Nodes to bootstrap</label>
                <div className="flex gap-2">
                  <button type="button"
                    onClick={() => setCheckedIds(new Set(groupMembers.map((n) => n.id)))}
                    className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                    Select all
                  </button>
                  <button type="button"
                    onClick={() => setCheckedIds(new Set())}
                    className="text-xs text-gray-500 hover:text-gray-700 font-medium">
                    Clear
                  </button>
                </div>
              </div>
              <div className="border border-gray-200 rounded-lg max-h-56 overflow-y-auto">
                {groupMembers.length === 0 && (
                  <p className="px-3 py-4 text-sm text-gray-400 text-center">
                    {groupMembersPage ? 'No nodes in this group' : 'Loading…'}
                  </p>
                )}
                {groupMembers.map((n) => {
                  const bs = (n as Node & { bootstrap_status?: string }).bootstrap_status
                  return (
                    <label key={n.id} className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 border-b border-gray-100 last:border-0 cursor-pointer">
                      <input type="checkbox" checked={checkedIds.has(n.id)}
                        onChange={(e) => {
                          const next = new Set(checkedIds)
                          if (e.target.checked) { next.add(n.id) } else { next.delete(n.id) }
                          setCheckedIds(next)
                        }} />
                      <span className="flex-1 text-sm font-medium text-gray-900">{n.hostname ?? n.minion_id}</span>
                      <span className="text-xs text-gray-400">{n.ip_address}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                        bs === 'completed' ? 'bg-green-100 text-green-700' :
                        bs === 'failed' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-500'
                      }`}>{bs ?? 'never'}</span>
                    </label>
                  )
                })}
              </div>
              {checkedIds.size > 0 && (
                <p className="text-xs text-gray-500 mt-1">{checkedIds.size} node{checkedIds.size !== 1 ? 's' : ''} selected</p>
              )}
            </div>
          )}

          <p className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-lg p-3">
            All jobs launch in parallel. Remote Login (SSH) must be enabled on each node.
            Credentials are taken from the node → group → global settings chain.
          </p>
          <div className="flex gap-3">
            <button type="button" onClick={onClose}
              className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
              Cancel
            </button>
            <button
              disabled={checkedIds.size === 0 || launching}
              onClick={launchFromGroup}
              className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
              {launching ? 'Launching…' : `Bootstrap ${checkedIds.size || ''} node${checkedIds.size !== 1 ? 's' : ''}`}
            </button>
          </div>
        </div>
      ) : (
        /* ── CSV mode (original) ── */
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
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600 font-mono resize-none"
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
              onClick={launchFromCsv}
              className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
              {launching ? 'Launching…' : `Bootstrap ${parsedRows.length || ''} nodes`}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Modal shell ──────────────────────────────────────────────────────────────

export function BootstrapModal({ onClose }: Props) {
  const [mode, setMode] = useState<Mode>('single')
  const containerRef = useFocusTrap<HTMLDivElement>(true, onClose)

  return (
    <div ref={containerRef} className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl flex flex-col max-h-[95vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 shrink-0">
          <h2 className="text-lg font-bold text-gray-900">Bootstrap Node</h2>
          <button onClick={onClose} className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-lg">×</button>
        </div>

        {/* Mode tabs */}
        <div className="px-6 pt-4 shrink-0">
          <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mb-4">
            {(['single', 'bulk'] as Mode[]).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  mode === m ? 'bg-white text-gray-900 shadow-xs' : 'text-gray-500 hover:text-gray-700'
                }`}>
                {m === 'single' ? 'Single node' : 'Bulk (multiple nodes)'}
              </button>
            ))}
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 pb-6">
          {mode === 'single' ? <SingleMode onClose={onClose} /> : <BulkMode onClose={onClose} />}
        </div>
      </div>
    </div>
  )
}
