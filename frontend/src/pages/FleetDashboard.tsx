import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { api } from '../api/client'
import { iosTrackingApi } from '../api/iosTracking'
import { useAuthStore } from '../stores/authStore'
import { useToastStore } from '../stores/toastStore'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { BootstrapModal } from './BootstrapModal'
import { formatDistanceToNow, differenceInDays, parseISO } from 'date-fns'
import type { Node } from '../types'

function isMacOSNode(node: Node): boolean {
  return !!(node.macos_version || node.xcode_version)
}

// ─── Add Node modal ────────────────────────────────────────────────────────────

function AddNodeModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [minionId, setMinionId] = useState('')
  const [hostname, setHostname] = useState('')
  const [ipAddress, setIpAddress] = useState('')
  const [groupId, setGroupId] = useState('')

  const { data: groups } = useQuery({
    queryKey: ['groups-for-add-node'],
    queryFn: () => groupsApi.list({ per_page: 100 }),
    staleTime: 60_000,
  })

  const mutation = useMutation({
    mutationFn: async () => {
      const node = await fleetApi.createNode({
        minion_id: minionId.trim(),
        hostname: hostname.trim() || undefined,
        ip_address: ipAddress.trim() || undefined,
      })
      await groupsApi.addMember(groupId, node.id)
      return node
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
      toast('Node added and assigned to group')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const canSubmit = minionId.trim() && groupId && !mutation.isPending

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">Add Node</h2>
          <button onClick={onClose} className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 text-lg">×</button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Minion ID <span className="text-red-500">*</span>
            </label>
            <input
              required
              value={minionId}
              onChange={(e) => setMinionId(e.target.value)}
              placeholder="mac-mini-01"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Group <span className="text-red-500">*</span>
            </label>
            <select
              required
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 bg-white"
            >
              <option value="">Select a group…</option>
              {(groups?.items ?? []).filter(g => g.type === 'static').map(g => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
            {(groups?.items ?? []).filter(g => g.type === 'static').length === 0 && (
              <p className="text-xs text-amber-600 mt-1">No static groups yet — <a href="/groups" className="underline">create one first</a>.</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Hostname <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
              placeholder="mac-mini-01.local"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              IP Address <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              value={ipAddress}
              onChange={(e) => setIpAddress(e.target.value)}
              placeholder="192.168.1.50"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-3">
          <button onClick={onClose} className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Cancel
          </button>
          <button
            disabled={!canSubmit}
            onClick={() => mutation.mutate()}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'Adding…' : 'Add Node'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Edit Node modal ───────────────────────────────────────────────────────────

function EditNodeModal({ node, onClose }: { node: Node; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [hostname, setHostname] = useState(node.hostname ?? '')
  const [ipAddress, setIpAddress] = useState(node.ip_address ?? node.bootstrap_ip ?? '')
  const [hardwareModel, setHardwareModel] = useState(node.hardware_model ?? '')
  const [osVersion, setOsVersion] = useState(node.os_version ?? '')
  const [authMode, setAuthMode] = useState<'password' | 'key'>(node.ssh_auth_mode ?? 'password')
  const [sshUsername, setSshUsername] = useState(node.ssh_username ?? '')
  const [sshPassword, setSshPassword] = useState('')
  const [sshKey, setSshKey] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      fleetApi.updateNode(node.id, {
        hostname: hostname.trim() || undefined,
        ip_address: ipAddress.trim() || undefined,
        hardware_model: hardwareModel.trim() || undefined,
        os_version: osVersion.trim() || undefined,
        ssh_username: sshUsername || undefined,
        ssh_password: sshPassword || undefined,
        ssh_auth_mode: authMode,
        ssh_key: sshKey || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: [`node-${node.id}`] })
      toast('Node updated')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md flex flex-col max-h-[95vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Edit Node</h2>
            <p className="text-xs text-gray-400 mt-0.5 font-mono">{node.minion_id}</p>
          </div>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-lg"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hostname</label>
            <input
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
              placeholder="mac-mini-01.local"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">IP Address</label>
            <input
              value={ipAddress}
              onChange={(e) => setIpAddress(e.target.value)}
              placeholder="192.168.1.50"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hardware Model</label>
            <input
              value={hardwareModel}
              onChange={(e) => setHardwareModel(e.target.value)}
              placeholder="Mac mini (2023)"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">OS Version</label>
            <input
              value={osVersion}
              onChange={(e) => setOsVersion(e.target.value)}
              placeholder="macOS 14.4.1"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>

          {/* Group membership notice */}
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
            <span className="text-amber-500 text-base mt-0.5">⚠</span>
            <p className="text-xs text-amber-700">
              This node must be added to a group before bootstrapping. Go to{' '}
              <a href="/groups" className="underline font-medium">Groups</a> to assign it and configure SSH credentials.
            </p>
          </div>

          {/* SSH Access */}
          <div className="border-t border-gray-100 pt-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">SSH Access (Node-level Override)</p>
            <p className="text-xs text-gray-400">
              Leave blank to inherit from the node's primary group. Node-level credentials take precedence over group credentials.
            </p>

            {/* Auth mode toggle */}
            <div className="flex gap-3">
              {(['password', 'key'] as const).map((mode) => (
                <label key={mode} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="radio" name="authMode" value={mode}
                    checked={authMode === mode}
                    onChange={() => setAuthMode(mode)}
                    className="accent-brand-600" />
                  {mode === 'password' ? 'Password auth' : 'SSH key auth'}
                </label>
              ))}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SSH Username</label>
              <input value={sshUsername} onChange={(e) => setSshUsername(e.target.value)}
                placeholder="admin"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
            </div>

            {authMode === 'password' ? (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Password {node.has_ssh_password && <span className="text-gray-400 font-normal">(saved — leave blank to keep)</span>}
                </label>
                <input type="password" value={sshPassword} onChange={(e) => setSshPassword(e.target.value)}
                  placeholder={node.has_ssh_password ? '••••••••' : 'Enter password'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Private Key {node.has_ssh_key && <span className="text-gray-400 font-normal">(saved — paste to replace)</span>}
                </label>
                <textarea rows={6} value={sshKey} onChange={(e) => setSshKey(e.target.value)}
                  placeholder={'-----BEGIN OPENSSH PRIVATE KEY-----\n...'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono text-gray-900 focus:outline-none focus:border-brand-600 resize-none" />
                <p className="text-xs text-gray-400 mt-1">Paste the private key. The public key will be authorized on the node automatically during bootstrap.</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 shrink-0">
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              disabled={mutation.isPending}
              onClick={() => mutation.mutate()}
              className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
            >
              {mutation.isPending ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Delete confirmation dialog ────────────────────────────────────────────────

function DeleteNodeDialog({ node, onClose }: { node: Node; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const mutation = useMutation({
    mutationFn: () => fleetApi.deleteNode(node.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
      toast('Node deleted')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const displayName = node.hostname ?? node.minion_id

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">Delete Node</h2>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-lg"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          <p className="text-sm text-gray-700">
            Delete <span className="font-semibold font-mono">{displayName}</span>? This will remove
            the node and all its history.
          </p>
          <p className="text-xs text-red-600 mt-2">This action cannot be undone.</p>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200">
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              disabled={mutation.isPending}
              onClick={() => mutation.mutate()}
              className="flex-1 py-2.5 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
            >
              {mutation.isPending ? 'Deleting…' : 'Delete Node'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function FleetDashboard() {
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(50)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [osFilter, setOsFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [driftMin, setDriftMin] = useState('')
  const [driftMax, setDriftMax] = useState('')
  const [sort, setSort] = useState('drift_score:desc')
  const [showBootstrap, setShowBootstrap] = useState(false)
  const [showAddNode, setShowAddNode] = useState(false)
  const [editingNode, setEditingNode] = useState<Node | null>(null)
  const [deletingNode, setDeletingNode] = useState<Node | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [bulkGraining, setBulkGraining] = useState(false)
  const [bulkScanning, setBulkScanning] = useState(false)
  const [bulkApplying, setBulkApplying] = useState(false)
  const [showSaltStateDropdown, setShowSaltStateDropdown] = useState(false)
  const [macosOnly, setMacosOnly] = useState(false)

  const user = useAuthStore((s) => s.user)
  const canManage = user?.role === 'admin' || user?.role === 'operator'

  const filters = { search, statusFilter, osFilter, tagFilter, driftMin, driftMax, sort }

  function resetFilters() {
    setSearch(''); setStatusFilter(''); setOsFilter('')
    setTagFilter(''); setDriftMin(''); setDriftMax(''); setSort('drift_score:desc')
    setMacosOnly(false)
    setPage(1)
  }

  const hasActiveFilters = search || statusFilter || osFilter || tagFilter || driftMin || driftMax || macosOnly

  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const { data: overview, isLoading: ovLoading } = useQuery({
    queryKey: ['fleet-overview'],
    queryFn: fleetApi.overview,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  const {
    data: nodes,
    isLoading: nodesLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['nodes', page, perPage, filters],
    queryFn: () => fleetApi.nodes({
      page, per_page: perPage,
      status: statusFilter || undefined,
      search: search || undefined,
      os_version: osFilter || undefined,
      tag: tagFilter || undefined,
      drift_min: driftMin ? parseInt(driftMin) : undefined,
      drift_max: driftMax ? parseInt(driftMax) : undefined,
      sort,
    }),
    staleTime: 30_000,
  })

  const { data: saltStatesData } = useQuery({
    queryKey: ['salt-states'],
    queryFn: () => api.get<{ states: Array<{ name: string; path: string }> }>('/api/v1/salt/states'),
    staleTime: 60_000,
    enabled: showSaltStateDropdown,
  })

  const { data: expiringCertsData } = useQuery({
    queryKey: ['ios-expiring-certs-fleet'],
    queryFn: () => iosTrackingApi.getExpiringCerts(60),
    staleTime: 300_000,
    enabled: macosOnly,
  })

  const certUrgency = useMemo(() => {
    const map = new Map<string, 'critical' | 'warning' | 'ok'>()
    for (const cert of expiringCertsData?.items ?? []) {
      const d = differenceInDays(parseISO(cert.expiry_date), new Date())
      const level = d < 30 ? 'critical' : d < 60 ? 'warning' : 'ok'
      const prev = map.get(cert.node_id)
      if (!prev || prev === 'ok' || (prev === 'warning' && level === 'critical')) {
        map.set(cert.node_id, level)
      }
    }
    return map
  }, [expiringCertsData])

  // Bulk select helpers — defined after nodes query so nodes is in scope
  const allIds = nodes?.items.map((n) => n.id) ?? []
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id))
  const someSelected = selected.size > 0

  function toggleAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(allIds))
  }

  function toggleOne(id: string) {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  async function bulkDelete() {
    const count = selected.size
    setBulkDeleting(true)
    let failed = 0
    await Promise.allSettled([...selected].map(id =>
      fleetApi.deleteNode(id).catch(() => { failed++ })
    ))
    setBulkDeleting(false)
    setSelected(new Set())
    qc.invalidateQueries({ queryKey: ['nodes'] })
    qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    toast(failed ? `Deleted with ${failed} error(s)` : `Deleted ${count} node(s)`, failed ? 'error' : 'success')
  }

  async function bulkCollectGrains() {
    setBulkGraining(true)
    const ids = [...selected]
    for (let i = 0; i < ids.length; i++) {
      try {
        await api.post(`/api/v1/ansible/nodes/${ids[i]}/collect-grains`)
        if (i < ids.length - 1) await new Promise((r) => setTimeout(r, 500))
      } catch { /* continue */ }
    }
    setBulkGraining(false)
    toast(`Queued grain collection for ${ids.length} node(s)`)
  }

  async function bulkTriggerSBOM() {
    setBulkScanning(true)
    const ids = [...selected]
    for (let i = 0; i < ids.length; i++) {
      try {
        await api.post(`/api/v1/security/scan/${ids[i]}?scanner=trivy`, {})
        if (i < ids.length - 1) await new Promise((r) => setTimeout(r, 500))
      } catch { /* continue */ }
    }
    setBulkScanning(false)
    toast(`Queued SBOM scan for ${ids.length} node(s)`)
  }

  async function bulkApplySaltState(state: string) {
    if (!state) return
    setBulkApplying(true)
    const selectedNodes = nodes?.items.filter((n) => selected.has(n.id)) ?? []
    const minionIds = selectedNodes.map((n) => n.minion_id)
    try {
      await api.post('/api/v1/salt/apply', { minion_ids: minionIds, state })
      toast(`Applied state '${state}' to ${minionIds.length} node(s)`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to apply state'
      toast(msg, 'error')
    }
    setBulkApplying(false)
    setShowSaltStateDropdown(false)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>
        <div className="flex items-center gap-2">
          {canManage && (
            <button
              onClick={() => setShowAddNode(true)}
              className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 shadow-sm"
            >
              + Add Node
            </button>
          )}
          <button
            onClick={() => setShowBootstrap(true)}
            className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
          >
            + Bootstrap Node
          </button>
        </div>
      </div>

      {/* Stat cards */}
      {ovLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : overview ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Nodes',    value: overview.total_nodes,                    accent: 'border-l-brand-600',   num: 'text-gray-900' },
            { label: 'Online',         value: overview.online,                         accent: 'border-l-emerald-500', num: 'text-emerald-700' },
            { label: 'Offline / Stale',value: overview.offline + overview.stale,       accent: 'border-l-red-500',     num: 'text-red-700' },
            { label: 'Avg Drift Score',value: overview.avg_drift_score,                accent: 'border-l-amber-500',   num: 'text-amber-700' },
          ].map(({ label, value, accent, num }) => (
            <div key={label} className={`bg-white rounded-xl border border-gray-200 border-l-4 ${accent} p-5 shadow-sm`}>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">{label}</p>
              <p className={`text-4xl font-bold tabular-nums ${num}`}>{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      {/* Filter bar */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
        {/* Row 1: search + status + OS */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 min-w-[180px]">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><circle cx="11" cy="11" r="8"/><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35"/></svg>
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }}
              placeholder="Search hostname or minion ID…"
              className="w-full pl-9 pr-3 py-1.5 border border-gray-300 text-sm text-gray-900 rounded-lg focus:outline-none focus:border-brand-600"
            />
          </div>

          {/* Status */}
          <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
            className="text-sm bg-white border border-gray-300 text-gray-900 rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-600">
            <option value="">All statuses</option>
            <option value="online">Online</option>
            <option value="offline">Offline</option>
            <option value="stale">Stale</option>
            <option value="unknown">Unknown</option>
          </select>

          {/* OS Version */}
          <input value={osFilter} onChange={(e) => { setOsFilter(e.target.value); setPage(1) }}
            placeholder="OS (e.g. 14.4)"
            className="w-36 px-3 py-1.5 border border-gray-300 text-sm text-gray-900 rounded-lg focus:outline-none focus:border-brand-600" />

          {/* Tag filter */}
          <input value={tagFilter} onChange={(e) => { setTagFilter(e.target.value); setPage(1) }}
            placeholder="Tag key:value"
            className="w-40 px-3 py-1.5 border border-gray-300 text-sm text-gray-900 rounded-lg focus:outline-none focus:border-brand-600" />

          {/* macOS toggle */}
          <button
            onClick={() => { setMacosOnly((v) => !v); setPage(1) }}
            className={`px-3 py-1.5 text-sm rounded-lg border font-medium transition-colors ${
              macosOnly
                ? 'bg-gray-900 text-white border-gray-900'
                : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
            }`}
          >
            macOS
          </button>
        </div>

        {/* Row 2: drift range + sort + reset */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-gray-500 font-medium">Drift:</span>
          <input value={driftMin} onChange={(e) => { setDriftMin(e.target.value); setPage(1) }}
            placeholder="Min" type="number" min="0"
            className="w-20 px-3 py-1.5 border border-gray-300 text-sm text-gray-900 rounded-lg focus:outline-none focus:border-brand-600" />
          <span className="text-gray-400 text-sm">–</span>
          <input value={driftMax} onChange={(e) => { setDriftMax(e.target.value); setPage(1) }}
            placeholder="Max" type="number" min="0"
            className="w-20 px-3 py-1.5 border border-gray-300 text-sm text-gray-900 rounded-lg focus:outline-none focus:border-brand-600" />

          <div className="flex-1" />

          {/* Sort */}
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }}
            className="text-sm bg-white border border-gray-300 text-gray-900 rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-600">
            <option value="drift_score:desc">Drift ↓</option>
            <option value="drift_score:asc">Drift ↑</option>
            <option value="hostname:asc">Hostname A–Z</option>
            <option value="hostname:desc">Hostname Z–A</option>
            <option value="last_seen_at:desc">Last Seen ↓</option>
            <option value="last_seen_at:asc">Last Seen ↑</option>
            <option value="status:asc">Status A–Z</option>
          </select>

          {/* Reset */}
          {hasActiveFilters && (
            <button onClick={resetFilters}
              className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50">
              ✕ Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Node table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {nodesLoading ? (
          <Skeleton rows={10} />
        ) : isError ? (
          <ErrorState message="Failed to load nodes" retry={refetch} />
        ) : (
          <>
            {nodes?.items.length === 0 ? (
              <div className="px-4 py-16 text-center space-y-4">
                <p className="text-4xl">🖥️</p>
                <p className="text-lg font-semibold text-gray-700">No nodes in your fleet yet</p>
                <p className="text-sm text-gray-500 max-w-sm mx-auto">
                  Bootstrap a Mac Mini to get started. Make sure Remote Login (SSH) is enabled on the device first.
                </p>
                <button
                  onClick={() => setShowBootstrap(true)}
                  className="px-6 py-2.5 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
                >
                  Bootstrap your first node →
                </button>
              </div>
            ) : (
              <>
                {/* Bulk action bar */}
                {someSelected && canManage && (
                  <div className="flex items-center flex-wrap gap-2 px-4 py-2 bg-brand-50 border-b border-brand-200">
                    <span className="text-sm font-medium text-brand-700">{selected.size} selected</span>
                    <button
                      onClick={bulkCollectGrains}
                      disabled={bulkGraining}
                      className="px-3 py-1 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 disabled:opacity-50"
                    >
                      {bulkGraining ? 'Collecting…' : 'Collect Grains'}
                    </button>
                    <button
                      onClick={bulkTriggerSBOM}
                      disabled={bulkScanning}
                      className="px-3 py-1 bg-purple-600 text-white text-xs font-medium rounded-lg hover:bg-purple-700 disabled:opacity-50"
                    >
                      {bulkScanning ? 'Queuing…' : 'SBOM Scan'}
                    </button>
                    <div className="relative">
                      <button
                        onClick={() => setShowSaltStateDropdown(!showSaltStateDropdown)}
                        className="px-3 py-1 bg-emerald-600 text-white text-xs font-medium rounded-lg hover:bg-emerald-700"
                      >
                        Apply Salt State ▾
                      </button>
                      {showSaltStateDropdown && (
                        <div className="absolute left-0 top-full mt-1 z-30 bg-white border border-gray-200 rounded-lg shadow-lg min-w-[200px] py-1">
                          {(saltStatesData?.states ?? []).length === 0 ? (
                            <p className="px-3 py-2 text-xs text-gray-400">No states found</p>
                          ) : (
                            (saltStatesData?.states ?? []).map((s) => (
                              <button
                                key={s.name}
                                onClick={() => bulkApplySaltState(s.name)}
                                disabled={bulkApplying}
                                className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 font-mono disabled:opacity-50"
                              >
                                {s.name}
                              </button>
                            ))
                          )}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={bulkDelete}
                      disabled={bulkDeleting}
                      className="px-3 py-1 bg-red-600 text-white text-xs font-medium rounded-lg hover:bg-red-700 disabled:opacity-50"
                    >
                      {bulkDeleting ? 'Deleting…' : `Delete ${selected.size}`}
                    </button>
                    <button onClick={() => { setSelected(new Set()); setShowSaltStateDropdown(false) }}
                      className="text-xs text-brand-600 hover:text-brand-800 ml-1">
                      Clear selection
                    </button>
                  </div>
                )}
                {(() => {
                  const displayedNodes = macosOnly
                    ? (nodes?.items ?? []).filter(isMacOSNode)
                    : (nodes?.items ?? [])
                  return (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      {canManage && (
                        <th className="pl-4 py-3 w-8">
                          <input type="checkbox" checked={allSelected} onChange={toggleAll}
                            className="accent-brand-600 cursor-pointer" />
                        </th>
                      )}
                      <th className="px-4 py-3">Hostname</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">OS</th>
                      <th className="px-4 py-3">Drift</th>
                      <th className="px-4 py-3">Last Seen</th>
                      <th className="px-4 py-3">Tags</th>
                      {macosOnly && <th className="px-4 py-3">Xcode</th>}
                      {macosOnly && <th className="px-4 py-3">Certs</th>}
                      {canManage && <th className="px-4 py-3 w-24"></th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {displayedNodes.map((node) => (
                      <tr key={node.id} data-testid={node.minion_id} className={`hover:bg-gray-50 transition-colors ${selected.has(node.id) ? 'bg-brand-50/40' : ''}`}>
                        {canManage && (
                          <td className="pl-4 py-3 w-8">
                            <input type="checkbox" checked={selected.has(node.id)}
                              onChange={() => toggleOne(node.id)}
                              className="accent-brand-600 cursor-pointer" />
                          </td>
                        )}
                        <td className="px-4 py-3 font-medium font-mono text-xs">
                          <Link to={`/nodes/${node.id}`} className="text-brand-600 hover:text-brand-700 hover:underline">
                            {node.hostname ?? node.minion_id}
                          </Link>
                          {(node.ip_address ?? node.bootstrap_ip) && (
                            <p className="text-gray-400 font-normal mt-0.5">{node.ip_address ?? node.bootstrap_ip}</p>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <StatusBadge status={node.status} />
                            {node.maintenance_mode && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200">⚙ Maint.</span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-gray-600">{node.os_version ?? '—'}</td>
                        <td className="px-4 py-3">
                          <DriftBadge score={node.drift_score} />
                        </td>
                        <td className="px-4 py-3 text-gray-500">
                          {node.last_seen_at
                            ? formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true })
                            : '—'}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {node.tags.map((t) => (
                              <span key={t.key}
                                title={t.source === 'system' ? 'Auto-populated from Salt' : undefined}
                                className={`text-xs border px-1.5 py-0.5 rounded ${
                                  t.source === 'system'
                                    ? 'bg-brand-50 text-brand-700 border-brand-200'
                                    : 'bg-gray-100 text-gray-600 border-gray-200'
                                }`}>
                                {t.key}={t.value}
                              </span>
                            ))}
                          </div>
                        </td>
                        {macosOnly && (
                          <td className="px-4 py-2 font-mono text-xs text-gray-600">
                            {node.xcode_version ?? '—'}
                          </td>
                        )}
                        {macosOnly && (
                          <td className="px-4 py-2">
                            {(() => {
                              const urgency = certUrgency.get(node.id)
                              if (!urgency) return <span className="text-gray-300 text-xs">—</span>
                              const cls = urgency === 'critical' ? 'bg-red-500' : urgency === 'warning' ? 'bg-amber-400' : 'bg-emerald-500'
                              return <span className={`w-2 h-2 rounded-full ${cls} inline-block`} title={urgency} />
                            })()}
                          </td>
                        )}
                        {canManage && (
                          <td className="px-4 py-3 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button onClick={() => setEditingNode(node)}
                                className="text-xs text-brand-600 hover:text-brand-700 font-medium">Edit</button>
                              <button onClick={() => setDeletingNode(node)}
                                className="text-xs text-red-500 hover:text-red-700 font-medium">Delete</button>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
                  )
                })()}
                {nodes && (
                  <Pagination page={page} total={nodes.total} perPage={nodes.per_page} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1) }} />
                )}
              </>
            )}
          </>
        )}
      </div>

      {showBootstrap && <BootstrapModal onClose={() => setShowBootstrap(false)} />}
      {showAddNode && <AddNodeModal onClose={() => setShowAddNode(false)} />}
      {editingNode && <EditNodeModal node={editingNode} onClose={() => setEditingNode(null)} />}
      {deletingNode && <DeleteNodeDialog node={deletingNode} onClose={() => setDeletingNode(null)} />}
    </div>
  )
}
