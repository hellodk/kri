/**
 * Salt Masters settings tab — issue #533, epic #537.
 *
 * Full CRUD: list + health/test (viewer+), create/edit/delete + set-default (admin).
 * Provision / Reconfigure button + live LogPane added in #558 (master-lifecycle epic phase 3).
 */

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link2 } from 'lucide-react'
import { saltMastersApi, type SaltMaster, type SaltMasterUpdate, type MasterMinionItem } from '../api/saltMasters'
import { fleetApi } from '../api/fleet'
import { saltMasterBadge } from '../lib/saltMasterHelpers'
import { provisionRefetchInterval } from '../lib/provisionPolling'
import { LogPane } from '../lib/LogPane'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SecretInput } from '../components/SecretInput'
import { formatLocalDateTime } from '../utils/time'

// ---------------------------------------------------------------------------
// Timestamp helpers
// ---------------------------------------------------------------------------

function formatTimestamp(isoString: string): string {
  return formatLocalDateTime(isoString, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function relativeTime(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return `${Math.floor(diffHr / 24)}d ago`
}

// ---------------------------------------------------------------------------
// Styling helpers
// ---------------------------------------------------------------------------

const checkStatusPill = (status: string) => {
  switch (status) {
    case 'pass':
      return 'bg-emerald-100 text-emerald-800 border border-emerald-200'
    case 'fail':
      return 'bg-red-100 text-red-800 border border-red-200'
    case 'warn':
      return 'bg-amber-100 text-amber-800 border border-amber-200'
    default:
      return 'bg-gray-100 text-gray-700 border border-gray-200'
  }
}

function provisionStatusBadge(status: string): { bgClass: string; textClass: string; label: string } {
  switch (status) {
    case 'provisioned':
      return { bgClass: 'bg-emerald-100', textClass: 'text-emerald-800', label: 'Provisioned' }
    case 'provisioning':
      return { bgClass: 'bg-blue-100', textClass: 'text-blue-800', label: 'Provisioning…' }
    case 'failed':
      return { bgClass: 'bg-red-100', textClass: 'text-red-800', label: 'Failed' }
    case 'degraded':
      return { bgClass: 'bg-amber-100', textClass: 'text-amber-800', label: 'Degraded' }
    case 'unprovisioned':
    default:
      return { bgClass: 'bg-gray-100', textClass: 'text-gray-600', label: 'Unprovisioned' }
  }
}

const inputClass =
  'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600 bg-white disabled:bg-gray-50 disabled:text-gray-500'

const labelClass = 'block text-xs font-semibold text-gray-700 mb-1'

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

interface FormState {
  name: string
  address: string
  enabled: boolean
  is_default: boolean
  publish_port: string
  ret_port: string
  /** SSoT fields (#562): api_url is derived from these; not a form input */
  salt_api_port: string
  use_tls: boolean
  api_user: string
  api_password: string
  tls_verify: boolean
  auto_accept: boolean
}

function masterToForm(m: SaltMaster): FormState {
  return {
    name: m.name,
    address: m.address,
    enabled: m.enabled,
    is_default: m.is_default,
    publish_port: String(m.publish_port),
    ret_port: String(m.ret_port),
    salt_api_port: String(m.salt_api_port),
    use_tls: m.use_tls,
    api_user: m.api_user ?? '',
    api_password: '', // never pre-filled — write-only
    tls_verify: m.tls_verify,
    auto_accept: m.auto_accept,
  }
}

/** Derive api_url preview from form fields — mirrors server logic (#562). */
function deriveApiUrl(address: string, saltApiPort: string, useTls: boolean): string {
  const scheme = useTls ? 'https' : 'http'
  const port = saltApiPort || '4507'
  const addr = address.trim() || '<address>'
  return `${scheme}://${addr}:${port}`
}

// ---------------------------------------------------------------------------
// MasterForm modal
// ---------------------------------------------------------------------------

interface MasterFormProps {
  initial: FormState
  title: string
  submitLabel: string
  isLoading: boolean
  error: string | null
  onSubmit: (form: FormState) => void
  onClose: () => void
}

function MasterForm({ initial, title, submitLabel, isLoading, error, onSubmit, onClose }: MasterFormProps) {
  const [form, setForm] = useState<FormState>(initial)

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSubmit(form)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-xl border border-gray-200 shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 sticky top-0 bg-white z-10">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {/* Name + Address */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass} htmlFor="sm-name">Name</label>
              <input
                id="sm-name"
                type="text"
                required
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="mm1"
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass} htmlFor="sm-address">Address</label>
              <input
                id="sm-address"
                type="text"
                required
                value={form.address}
                onChange={(e) => set('address', e.target.value)}
                placeholder="salt.local"
                className={inputClass + ' font-mono'}
              />
            </div>
          </div>

          {/* Ports */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass} htmlFor="sm-publish-port">Publish Port</label>
              <input
                id="sm-publish-port"
                type="number"
                min={1}
                max={65535}
                value={form.publish_port}
                onChange={(e) => set('publish_port', e.target.value)}
                className={inputClass + ' font-mono'}
              />
            </div>
            <div>
              <label className={labelClass} htmlFor="sm-ret-port">Return Port</label>
              <input
                id="sm-ret-port"
                type="number"
                min={1}
                max={65535}
                value={form.ret_port}
                onChange={(e) => set('ret_port', e.target.value)}
                className={inputClass + ' font-mono'}
              />
            </div>
          </div>

          {/* Salt API port + use_tls (SSoT fields #562) */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass} htmlFor="sm-salt-api-port">Salt API Port</label>
              <input
                id="sm-salt-api-port"
                type="number"
                min={1}
                max={65535}
                value={form.salt_api_port}
                onChange={(e) => set('salt_api_port', e.target.value)}
                className={inputClass + ' font-mono'}
              />
            </div>
            <div className="flex flex-col justify-end pb-0.5">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.use_tls}
                  onChange={(e) => set('use_tls', e.target.checked)}
                  className="rounded border-gray-300 text-brand-600 focus:ring-brand-600"
                />
                <span>
                  <span className="font-medium">salt-api uses HTTPS</span>
                </span>
              </label>
            </div>
          </div>

          {/* Derived api_url preview — read-only */}
          <div>
            <label className={labelClass}>API URL <span className="font-normal text-gray-400">(derived — read-only)</span></label>
            <div className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono text-gray-600 bg-gray-50">
              {deriveApiUrl(form.address, form.salt_api_port, form.use_tls)}
            </div>
          </div>

          {/* API user */}
          <div>
            <label className={labelClass} htmlFor="sm-api-user">API User</label>
            <input
              id="sm-api-user"
              type="text"
              value={form.api_user}
              onChange={(e) => set('api_user', e.target.value)}
              placeholder="saltadmin"
              className={inputClass}
            />
          </div>

          {/* API Password — write-only, never pre-filled */}
          <div>
            <label className={labelClass} htmlFor="sm-api-password">
              API Password
              <span className="ml-1 text-xs font-normal text-gray-500">(write-only — leave blank to keep existing)</span>
            </label>
            <SecretInput
              id="sm-api-password"
              value={form.api_password}
              onChange={(v) => set('api_password', v)}
              placeholder="••••••••"
              className={inputClass}
            />
          </div>

          {/* Flags */}
          <div className="flex gap-6 flex-wrap">
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => set('enabled', e.target.checked)}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-600"
              />
              Enabled
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => set('is_default', e.target.checked)}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-600"
              />
              Set as default
            </label>
          </div>

          {/* TLS + auto-accept */}
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-3">
            <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Security</p>
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.tls_verify}
                onChange={(e) => set('tls_verify', e.target.checked)}
                className="mt-0.5 rounded border-gray-300 text-brand-600 focus:ring-brand-600"
              />
              <span>
                <span className="text-sm font-medium text-gray-900">Verify TLS certificate</span>
                <span className="block text-xs text-gray-600 mt-0.5">
                  Leave off for self-signed certs. The <em>salt-api uses HTTPS</em> toggle above controls the URL scheme; this controls whether the cert is validated.
                </span>
              </span>
            </label>
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.auto_accept}
                onChange={(e) => set('auto_accept', e.target.checked)}
                className="mt-0.5 rounded border-gray-300 text-brand-600 focus:ring-brand-600"
              />
              <span>
                <span className="text-sm font-medium text-gray-900">Auto-accept minion key on bootstrap</span>
                <span className="block text-xs text-gray-600 mt-0.5">
                  kri calls <code className="font-mono bg-gray-100 px-1 rounded">key.accept</code> via salt-api after a successful bootstrap run.
                </span>
              </span>
            </label>
          </div>

          {error && (
            <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          {/* Footer */}
          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg transition-colors disabled:opacity-50"
            >
              {isLoading ? 'Saving…' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-master minions section (#560)
// ---------------------------------------------------------------------------

function minionStatusBadge(status: string): { bg: string; text: string } {
  switch (status) {
    case 'active':
    case 'online':
      return { bg: 'bg-emerald-100', text: 'text-emerald-800' }
    case 'offline':
      return { bg: 'bg-red-100', text: 'text-red-800' }
    case 'maintenance':
      return { bg: 'bg-amber-100', text: 'text-amber-800' }
    default:
      return { bg: 'bg-gray-100', text: 'text-gray-600' }
  }
}

interface MasterMinionsSectionProps {
  masterId: string
}

function MasterMinionsSection({ masterId }: MasterMinionsSectionProps) {
  const { data: minions, isLoading } = useQuery({
    queryKey: ['master-minions', masterId],
    queryFn: () => saltMastersApi.minions(masterId),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (isLoading) {
    return (
      <div className="border-t border-gray-100 px-5 py-3 text-xs text-gray-500 italic" role="status" aria-live="polite">
        Loading minions…
      </div>
    )
  }

  const list = minions ?? []

  return (
    <div className="border-t border-gray-100">
      <div className="px-5 py-2.5 bg-gray-50 flex items-center gap-2">
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-gray-500 shrink-0"
          aria-hidden="true"
        >
          <rect x="2" y="3" width="20" height="14" rx="2" />
          <path d="M8 21h8M12 17v4" />
        </svg>
        <span className="text-xs font-semibold text-gray-700">
          Minions
        </span>
        <span className="ml-1 px-1.5 py-0.5 rounded-full bg-gray-200 text-gray-700 text-xs font-medium">
          {list.length}
        </span>
      </div>

      {list.length === 0 ? (
        <div className="px-5 py-3 text-xs text-gray-500 italic">
          No nodes are currently assigned to this master.
        </div>
      ) : (
        <div className="divide-y divide-gray-100">
          {list.map((m: MasterMinionItem) => {
            const badge = minionStatusBadge(m.status)
            return (
              <div
                key={m.id}
                className="px-5 py-2.5 flex items-center justify-between gap-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sm font-medium text-gray-900 truncate">
                    {m.hostname ?? m.minion_id}
                  </span>
                  {m.hostname && (
                    <span className="text-xs text-gray-400 font-mono truncate hidden sm:block">
                      {m.minion_id}
                    </span>
                  )}
                </div>
                <span
                  className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-semibold border border-transparent ${badge.bg} ${badge.text}`}
                >
                  {m.status}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Attach minions modal (#978) — multi-select of candidate fleet nodes,
// wired to the additive-HA backend at POST .../attach-minions (#977).
// ---------------------------------------------------------------------------

interface AttachMinionsModalProps {
  master: SaltMaster
  onClose: () => void
}

function AttachMinionsModal({ master, onClose }: AttachMinionsModalProps) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [defaultsApplied, setDefaultsApplied] = useState(false)

  // Candidate pool: reuse the same fleet-nodes list the Nodes/Bootstrap pages use.
  const { data: allNodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['all-nodes-for-attach'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    staleTime: 30_000,
  })

  // This master's current minions — used to exclude already-attached nodes
  // from the default selection (shares the cache key with MasterMinionsSection).
  const { data: currentMinions, isLoading: minionsLoading } = useQuery({
    queryKey: ['master-minions', master.id],
    queryFn: () => saltMastersApi.minions(master.id),
    staleTime: 30_000,
  })

  // A candidate is a bootstrapped node — i.e. it has a minion_id.
  const candidates = (allNodes?.items ?? []).filter((n) => !!n.minion_id)
  const attachedIds = new Set((currentMinions ?? []).map((m) => m.id))

  // Default-select candidates NOT already on this master, once both queries land.
  useEffect(() => {
    if (allNodes && currentMinions && !defaultsApplied) {
      setSelectedIds(new Set(candidates.filter((n) => !attachedIds.has(n.id)).map((n) => n.id)))
      setDefaultsApplied(true)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allNodes, currentMinions, defaultsApplied])

  const attachMutation = useMutation({
    mutationFn: (nodeIds: string[]) => saltMastersApi.attachMinions(master.id, nodeIds),
    onSuccess: (data) => {
      toast(`Re-pointing ${data.count} minion(s) — running in the background`, 'success')
      qc.invalidateQueries({ queryKey: ['master-minions', master.id] })
      onClose()
    },
    onError: (err: Error) => {
      toast(`Attach failed: ${err.message}`, 'error')
    },
  })

  const isLoading = nodesLoading || minionsLoading

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-xl border border-gray-200 shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-gray-200 sticky top-0 bg-white z-10">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Attach minions to {master.name}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Selected minions will also report to this master (additive HA).
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Candidate list */}
        <div className="px-6 py-4">
          {isLoading ? (
            <p className="px-3 py-4 text-sm text-gray-400 text-center">Loading nodes…</p>
          ) : candidates.length === 0 ? (
            <p className="px-3 py-4 text-sm text-gray-400 text-center">No bootstrapped nodes available.</p>
          ) : (
            <div className="border border-gray-200 rounded-lg max-h-80 overflow-y-auto divide-y divide-gray-100">
              {candidates.map((n) => {
                const checked = selectedIds.has(n.id)
                const alreadyAttached = attachedIds.has(n.id)
                return (
                  <label
                    key={n.id}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        const next = new Set(selectedIds)
                        if (e.target.checked) { next.add(n.id) } else { next.delete(n.id) }
                        setSelectedIds(next)
                      }}
                      className="rounded border-gray-300 text-brand-600 focus:ring-brand-600"
                    />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-gray-900 truncate block">
                        {n.hostname ?? n.minion_id}
                      </span>
                      <span className="text-xs text-gray-400 font-mono truncate block">
                        {n.ip_address ?? '—'}
                      </span>
                    </div>
                    {alreadyAttached && (
                      <span className="shrink-0 px-2 py-0.5 rounded-full text-xs font-medium bg-brand-100 text-brand-700 border border-brand-200">
                        On this master
                      </span>
                    )}
                  </label>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-200 sticky bottom-0 bg-white">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={selectedIds.size === 0 || attachMutation.isPending}
            onClick={() => attachMutation.mutate(Array.from(selectedIds))}
            className="px-4 py-2 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg transition-colors disabled:opacity-50"
          >
            {attachMutation.isPending
              ? 'Attaching…'
              : `Attach ${selectedIds.size} minion${selectedIds.size !== 1 ? 's' : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-master provision panel (LogPane + polling)
// ---------------------------------------------------------------------------

interface MasterProvisionPanelProps {
  masterId: string
  onRunStatusChange?: (status: string | undefined) => void
}

function MasterProvisionPanel({ masterId, onRunStatusChange }: MasterProvisionPanelProps) {
  const { data: run } = useQuery({
    queryKey: ['provision-status', masterId],
    queryFn: () => saltMastersApi.provisionStatus(masterId),
    refetchInterval: (query) => provisionRefetchInterval(query.state.data?.status),
  })

  // Notify parent of status changes for button disable state
  const status = run?.status
  if (onRunStatusChange) {
    onRunStatusChange(status)
  }

  const isRunning = status === 'running'

  return (
    <div className="flex flex-col h-[24rem] border-t border-gray-100">
      {/* Run header */}
      {run && (
        <div className="px-5 py-2.5 bg-gray-50 border-b border-gray-100 flex items-center gap-3 flex-wrap text-xs text-gray-600">
          <span>
            <span className="font-medium text-gray-700">Action:</span>{' '}
            <span className="font-mono">{run.action}</span>
          </span>
          <span>
            <span className="font-medium text-gray-700">Status:</span>{' '}
            <span
              className={`px-1.5 py-0.5 rounded font-semibold text-xs border ${
                run.status === 'completed'
                  ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                  : run.status === 'running'
                    ? 'bg-blue-100 text-blue-800 border-blue-200'
                    : run.status === 'failed'
                      ? 'bg-red-100 text-red-800 border-red-200'
                      : 'bg-gray-100 text-gray-700 border-gray-200'
              }`}
            >
              {run.status}
            </span>
          </span>
          <span>
            <span className="font-medium text-gray-700">Started:</span>{' '}
            <span title={relativeTime(run.started_at)}>
              {formatTimestamp(run.started_at)}
            </span>
          </span>
          {run.finished_at && (
            <span>
              <span className="font-medium text-gray-700">Finished:</span>{' '}
              <span title={relativeTime(run.finished_at)}>
                {formatTimestamp(run.finished_at)}
              </span>
            </span>
          )}
          {run.error && (
            <span className="text-red-700 font-mono truncate max-w-xs" title={run.error}>
              {run.error}
            </span>
          )}
        </div>
      )}
      {!run && (
        <div className="px-5 py-2.5 bg-gray-50 border-b border-gray-100 text-xs text-gray-500 italic">
          No provision runs yet. Click <strong>Provision / Reconfigure</strong> to start.
        </div>
      )}
      <LogPane
        raw={run?.ansible_stdout ?? ''}
        isLive={isRunning}
        emptyText="No output recorded yet."
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SaltMastersTab() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  // Modal state
  const [editMaster, setEditMaster] = useState<SaltMaster | null>(null)
  const [deleteMaster, setDeleteMaster] = useState<SaltMaster | null>(null)
  const [attachMaster, setAttachMaster] = useState<SaltMaster | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  // Provision panel: which master has the LogPane open
  const [provisionPanelId, setProvisionPanelId] = useState<string | null>(null)
  // Track which master is currently being provisioned (for button disable state)
  const [provisioningId, setProvisioningId] = useState<string | null>(null)

  const { data: masters, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => saltMastersApi.test(id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      if (data.status === 'healthy') {
        toast('Connection test passed — all checks healthy', 'success')
      } else {
        const firstFail = data.checks.find((c) => c.status === 'fail')
        const detail = firstFail ? firstFail.detail : 'check results below'
        toast(`Connection test failed: ${detail}`, 'error')
      }
    },
    onError: (err: Error) => {
      toast(`Test failed: ${err.message}`, 'error')
    },
  })

  const provisionMutation = useMutation({
    mutationFn: (id: string) => saltMastersApi.provision(id),
    onSuccess: (_data, id) => {
      setProvisioningId(id)
      setProvisionPanelId(id)
      toast('Provision task queued', 'success')
    },
    onError: (err: Error) => {
      setProvisioningId(null)
      toast(`Provision failed: ${err.message}`, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: SaltMasterUpdate }) =>
      saltMastersApi.update(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      toast('Salt master updated', 'success')
      setEditMaster(null)
      setFormError(null)
    },
    onError: (err: Error) => {
      setFormError(err.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => saltMastersApi.remove(id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      const msg =
        data?.nodes_reassigned > 0
          ? `Salt master deleted (${data.nodes_reassigned} node${data.nodes_reassigned === 1 ? '' : 's'} reassigned to "${data.reassigned_to}")`
          : 'Salt master deleted'
      toast(msg, 'success')
      setDeleteMaster(null)
    },
    onError: (err: Error) => {
      toast(`Delete failed: ${err.message}`, 'error')
      setDeleteMaster(null)
    },
  })

  function handleUpdate(form: FormState) {
    if (!editMaster) return
    setFormError(null)
    const body: SaltMasterUpdate = {
      name: form.name.trim(),
      address: form.address.trim(),
      enabled: form.enabled,
      is_default: form.is_default,
      publish_port: parseInt(form.publish_port, 10),
      ret_port: parseInt(form.ret_port, 10),
      // SSoT fields (#562): api_url is derived server-side; never sent
      salt_api_port: parseInt(form.salt_api_port, 10) || 4507,
      use_tls: form.use_tls,
      api_user: form.api_user.trim() || null,
      // Only send api_password if the operator typed something new
      ...(form.api_password ? { api_password: form.api_password } : {}),
      tls_verify: form.tls_verify,
      auto_accept: form.auto_accept,
    }
    updateMutation.mutate({ id: editMaster.id, body })
  }

  function handleSetDefault(master: SaltMaster) {
    updateMutation.mutate({ id: master.id, body: { is_default: true } })
  }

  if (isLoading) return <Skeleton rows={4} />

  if (isError) {
    return (
      <ErrorState
        message={(error as Error)?.message ?? 'Failed to load salt masters'}
        retry={() => refetch()}
      />
    )
  }

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Salt Masters</h2>
          <p className="text-sm text-gray-600 mt-1">
            Configured Salt API endpoints. Default first. New masters are created via Bootstrap
            (check &quot;Also make this node a salt-master&quot;).
          </p>
        </div>
      </div>

      {(!masters || masters.length === 0) && (
        <div className="py-12 text-center border border-dashed border-gray-300 rounded-xl">
          <div className="mx-auto w-12 h-12 mb-4 rounded-full bg-gray-100 flex items-center justify-center">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-gray-400" aria-hidden="true">
              <rect x="2" y="3" width="20" height="14" rx="2" />
              <path d="M8 21h8M12 17v4" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-gray-900 mb-1">No salt-master configured</h3>
          <p className="text-sm text-gray-600">
            Bootstrap a node with <strong>&quot;Also make this node a salt-master&quot;</strong> checked to create your first salt master.
          </p>
        </div>
      )}

      <div className="space-y-4">
        {masters?.map((master) => {
          const badge = saltMasterBadge(master.status)
          const isPending = testMutation.isPending && testMutation.variables === master.id
          const isProvisioning = provisioningId === master.id
          const isProvisionBtnDisabled =
            isProvisioning ||
            (provisionMutation.isPending && provisionMutation.variables === master.id)
          const provisionBadge = provisionStatusBadge(master.provision_status)
          const isLogPanelOpen = provisionPanelId === master.id

          const checks = Array.isArray(master.checks)
            ? master.checks as Array<{ check: string; status: string; detail: string; latency_ms: number }>
            : master.checks
              ? (Object.values(master.checks) as Array<{ check: string; status: string; detail: string; latency_ms: number }>)
              : []

          return (
            <div
              key={master.id}
              className="border border-gray-200 rounded-xl bg-white shadow-xs overflow-hidden"
            >
              {/* Header row */}
              <div className="px-5 py-4 flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-gray-900 truncate">
                      {master.name}
                    </span>
                    {master.is_default && (
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-brand-100 text-brand-700 border border-brand-200">
                        Default
                      </span>
                    )}
                    {!master.enabled && (
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-600 border border-gray-200">
                        Disabled
                      </span>
                    )}
                    <span
                      className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${badge.bgClass} ${badge.textClass}`}
                    >
                      {badge.label}
                    </span>
                    {/* Provision status badge */}
                    <span
                      className={`px-2 py-0.5 text-xs font-semibold rounded-full border border-transparent ${provisionBadge.bgClass} ${provisionBadge.textClass}`}
                      title="Provision status"
                    >
                      {provisionBadge.label}
                    </span>
                  </div>
                  <div className="mt-1 text-sm text-gray-600 font-mono truncate">
                    {master.address}
                    {master.api_url && (
                      <span className="ml-2 text-gray-400 font-sans text-xs">
                        · <span className="font-mono">{master.api_url}</span>
                        <span className="ml-1 text-gray-400 italic">(derived)</span>
                      </span>
                    )}
                  </div>
                </div>

                {/* Action buttons */}
                <div className="shrink-0 flex items-center gap-2 flex-wrap">
                  {!master.is_default && (
                    <button
                      type="button"
                      onClick={() => handleSetDefault(master)}
                      disabled={updateMutation.isPending}
                      className="px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
                      title="Promote this master to default"
                    >
                      Set default
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => testMutation.mutate(master.id)}
                    disabled={isPending}
                    className="px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
                    title="Run a live connectivity probe against this salt-master"
                  >
                    {isPending ? 'Testing…' : 'Test connection'}
                  </button>
                  {/* Attach minions — admin only (backend enforces) (#978) */}
                  <button
                    type="button"
                    onClick={() => setAttachMaster(master)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
                    title="Re-point selected fleet nodes at this master (additive HA)"
                  >
                    <Link2 size={14} />
                    Attach minions
                  </button>
                  {/* Provision / Reconfigure button — admin only (backend enforces) */}
                  <button
                    type="button"
                    onClick={() => {
                      provisionMutation.mutate(master.id)
                    }}
                    disabled={isProvisionBtnDisabled}
                    className="px-3 py-1.5 text-xs font-medium border border-indigo-300 text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg disabled:opacity-50 transition-colors"
                    title="Install or reconfigure salt-master on the SSH host"
                  >
                    {isProvisionBtnDisabled ? 'Provisioning…' : 'Provision / Reconfigure'}
                  </button>
                  {/* Toggle log panel */}
                  <button
                    type="button"
                    onClick={() => setProvisionPanelId(isLogPanelOpen ? null : master.id)}
                    className="px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
                    title={isLogPanelOpen ? 'Hide provision log' : 'Show provision log'}
                  >
                    {isLogPanelOpen ? 'Hide log' : 'Provision log'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setFormError(null); setEditMaster(master) }}
                    className="px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
                    title="Edit this salt-master"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteMaster(master)}
                    className="px-3 py-1.5 text-xs font-medium border border-red-200 text-red-700 rounded-lg hover:bg-red-50 transition-colors"
                    title="Delete this salt-master"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Meta row */}
              <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex flex-wrap gap-x-6 gap-y-1.5 text-xs text-gray-600">
                <span>
                  <span className="font-medium text-gray-700">Publish port:</span>{' '}
                  {master.publish_port}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Return port:</span>{' '}
                  {master.ret_port}
                </span>
                <span>
                  <span className="font-medium text-gray-700">API port:</span>{' '}
                  {master.salt_api_port}
                </span>
                <span>
                  <span className="font-medium text-gray-700">HTTPS:</span>{' '}
                  {master.use_tls ? 'yes' : 'no'}
                </span>
                {master.api_user && (
                  <span>
                    <span className="font-medium text-gray-700">API user:</span>{' '}
                    {master.api_user}
                  </span>
                )}
                {master.salt_version && (
                  <span>
                    <span className="font-medium text-gray-700">Salt version:</span>{' '}
                    <span className="font-mono">{master.salt_version}</span>
                  </span>
                )}
                {master.last_provisioned_at && (
                  <span>
                    <span className="font-medium text-gray-700">Provisioned:</span>{' '}
                    <span title={relativeTime(master.last_provisioned_at)}>
                      {formatTimestamp(master.last_provisioned_at)}
                    </span>
                  </span>
                )}
                <span>
                  <span className="font-medium text-gray-700">Last checked:</span>{' '}
                  {master.last_checked_at ? (
                    <span title={relativeTime(master.last_checked_at)}>
                      {formatTimestamp(master.last_checked_at)}
                    </span>
                  ) : (
                    <span className="text-gray-500 italic">never checked</span>
                  )}
                </span>
              </div>

              {/* Last error */}
              {master.last_error && (
                <div className="px-5 py-3 bg-red-50 border-t border-red-100 text-xs text-red-700 font-mono">
                  {master.last_error}
                </div>
              )}

              {/* Checks table */}
              {checks.length > 0 && (
                <div className="border-t border-gray-100">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-100">
                        <th scope="col" className="px-5 py-2 text-left font-semibold text-gray-700">Check</th>
                        <th scope="col" className="px-5 py-2 text-left font-semibold text-gray-700">Status</th>
                        <th scope="col" className="px-5 py-2 text-left font-semibold text-gray-700">Detail</th>
                        <th scope="col" className="px-5 py-2 text-right font-semibold text-gray-700">Latency</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {checks.map((chk) => (
                        <tr key={chk.check} className="hover:bg-gray-50">
                          <td className="px-5 py-2 font-mono text-gray-800">{chk.check}</td>
                          <td className="px-5 py-2">
                            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${checkStatusPill(chk.status)}`}>
                              {chk.status}
                            </span>
                          </td>
                          <td className="px-5 py-2 text-gray-600">{chk.detail}</td>
                          <td className="px-5 py-2 text-right font-mono text-gray-600">
                            {chk.latency_ms != null ? `${chk.latency_ms}ms` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Provision log panel — only shown when open */}
              {isLogPanelOpen && (
                <MasterProvisionPanel
                  masterId={master.id}
                  onRunStatusChange={(status) => {
                    // When run finishes/fails, clear the provisioning lock
                    if (status && status !== 'running' && provisioningId === master.id) {
                      setProvisioningId(null)
                    }
                  }}
                />
              )}

              {/* Minions topology — always visible (#560) */}
              <MasterMinionsSection masterId={master.id} />
            </div>
          )
        })}
      </div>

      {/* Edit modal */}
      {editMaster && (
        <MasterForm
          initial={masterToForm(editMaster)}
          title={`Edit — ${editMaster.name}`}
          submitLabel="Save changes"
          isLoading={updateMutation.isPending}
          error={formError}
          onSubmit={handleUpdate}
          onClose={() => { setEditMaster(null); setFormError(null) }}
        />
      )}

      {/* Attach minions modal (#978) */}
      {attachMaster && (
        <AttachMinionsModal
          master={attachMaster}
          onClose={() => setAttachMaster(null)}
        />
      )}

      {/* Delete confirm */}
      {deleteMaster && (
        <ConfirmDialog
          title={`Delete "${deleteMaster.name}"?`}
          message={`This will permanently remove the salt master "${deleteMaster.name}". Any nodes assigned to it will be automatically reassigned to the default master. This action cannot be undone.`}
          confirmLabel="Delete"
          destructive
          onConfirm={() => deleteMutation.mutate(deleteMaster.id)}
          onCancel={() => setDeleteMaster(null)}
        />
      )}
    </div>
  )
}
