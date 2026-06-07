/**
 * Salt Masters settings tab — issue #533, epic #537.
 *
 * Full CRUD: list + health/test (viewer+), create/edit/delete + set-default (admin).
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { saltMastersApi, type SaltMaster, type SaltMasterCreate, type SaltMasterUpdate } from '../api/saltMasters'
import { saltMasterBadge } from '../lib/saltMasterHelpers'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SecretInput } from '../components/SecretInput'

// ---------------------------------------------------------------------------
// Timestamp helpers
// ---------------------------------------------------------------------------

function formatIst(isoString: string): string {
  return (
    new Date(isoString).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }) + ' IST'
  )
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

const inputClass =
  'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 bg-white disabled:bg-gray-50 disabled:text-gray-500'

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
  control_mode: string
  api_url: string
  api_user: string
  api_password: string
  api_eauth: string
  token_delivery: string
}

const EMPTY_FORM: FormState = {
  name: '',
  address: '',
  enabled: true,
  is_default: false,
  publish_port: '4505',
  ret_port: '4506',
  control_mode: 'salt_api',
  api_url: '',
  api_user: '',
  api_password: '',
  api_eauth: '',
  token_delivery: 'ingest',
}

function masterToForm(m: SaltMaster): FormState {
  return {
    name: m.name,
    address: m.address,
    enabled: m.enabled,
    is_default: m.is_default,
    publish_port: String(m.publish_port),
    ret_port: String(m.ret_port),
    control_mode: m.control_mode,
    api_url: m.api_url ?? '',
    api_user: m.api_user ?? '',
    api_password: '', // never pre-filled — write-only
    api_eauth: m.api_eauth ?? '',
    token_delivery: m.token_delivery,
  }
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

          {/* Control mode + Token delivery */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass} htmlFor="sm-control-mode">Control Mode</label>
              <select
                id="sm-control-mode"
                value={form.control_mode}
                onChange={(e) => set('control_mode', e.target.value)}
                className={inputClass}
              >
                <option value="salt_api">salt_api</option>
                <option value="cli">cli</option>
              </select>
            </div>
            <div>
              <label className={labelClass} htmlFor="sm-token-delivery">Token Delivery</label>
              <select
                id="sm-token-delivery"
                value={form.token_delivery}
                onChange={(e) => set('token_delivery', e.target.value)}
                className={inputClass}
              >
                <option value="ingest">ingest</option>
                <option value="direct">direct</option>
              </select>
            </div>
          </div>

          {/* API URL */}
          <div>
            <label className={labelClass} htmlFor="sm-api-url">API URL</label>
            <input
              id="sm-api-url"
              type="url"
              value={form.api_url}
              onChange={(e) => set('api_url', e.target.value)}
              placeholder="https://salt.local:8080"
              className={inputClass + ' font-mono'}
            />
          </div>

          {/* API user + eAuth */}
          <div className="grid grid-cols-2 gap-4">
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
            <div>
              <label className={labelClass} htmlFor="sm-api-eauth">eAuth</label>
              <input
                id="sm-api-eauth"
                type="text"
                value={form.api_eauth}
                onChange={(e) => set('api_eauth', e.target.value)}
                placeholder="pam"
                className={inputClass}
              />
            </div>
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
          <div className="flex gap-6">
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
// Main component
// ---------------------------------------------------------------------------

export function SaltMastersTab() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  // Modal state
  const [showCreate, setShowCreate] = useState(false)
  const [editMaster, setEditMaster] = useState<SaltMaster | null>(null)
  const [deleteMaster, setDeleteMaster] = useState<SaltMaster | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const { data: masters, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => saltMastersApi.test(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      toast('Connection test completed', 'success')
    },
    onError: (err: Error) => {
      toast(`Test failed: ${err.message}`, 'error')
    },
  })

  const createMutation = useMutation({
    mutationFn: (body: SaltMasterCreate) => saltMastersApi.create(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      toast('Salt master created', 'success')
      setShowCreate(false)
      setFormError(null)
    },
    onError: (err: Error) => {
      setFormError(err.message)
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      toast('Salt master deleted', 'success')
      setDeleteMaster(null)
    },
    onError: (err: Error) => {
      toast(`Delete failed: ${err.message}`, 'error')
      setDeleteMaster(null)
    },
  })

  function handleCreate(form: FormState) {
    setFormError(null)
    const body: SaltMasterCreate = {
      name: form.name.trim(),
      address: form.address.trim(),
      enabled: form.enabled,
      is_default: form.is_default,
      publish_port: parseInt(form.publish_port, 10),
      ret_port: parseInt(form.ret_port, 10),
      control_mode: form.control_mode,
      api_url: form.api_url.trim() || null,
      api_user: form.api_user.trim() || null,
      api_password: form.api_password || null,
      api_eauth: form.api_eauth.trim() || null,
      token_delivery: form.token_delivery,
    }
    createMutation.mutate(body)
  }

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
      control_mode: form.control_mode,
      api_url: form.api_url.trim() || null,
      api_user: form.api_user.trim() || null,
      // Only send api_password if the operator typed something new
      ...(form.api_password ? { api_password: form.api_password } : {}),
      api_eauth: form.api_eauth.trim() || null,
      token_delivery: form.token_delivery,
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
            Configured Salt API endpoints. Default first.
          </p>
        </div>
        <button
          type="button"
          onClick={() => { setFormError(null); setShowCreate(true) }}
          className="shrink-0 px-3 py-1.5 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg transition-colors"
        >
          + Add master
        </button>
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
          <p className="text-sm text-gray-600">Click <strong>+ Add master</strong> to add your first salt master.</p>
        </div>
      )}

      <div className="space-y-4">
        {masters?.map((master) => {
          const badge = saltMasterBadge(master.status)
          const isPending = testMutation.isPending && testMutation.variables === master.id

          const checks = Array.isArray(master.checks)
            ? master.checks as Array<{ check: string; status: string; detail: string; latency_ms: number }>
            : master.checks
              ? (Object.values(master.checks) as Array<{ check: string; status: string; detail: string; latency_ms: number }>)
              : []

          return (
            <div
              key={master.id}
              className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden"
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
                  </div>
                  <div className="mt-1 text-sm text-gray-600 font-mono truncate">
                    {master.address}
                    {master.api_url && (
                      <span className="ml-2 text-gray-400 non-mono font-sans">
                        · {master.api_url}
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
                  <span className="font-medium text-gray-700">Mode:</span>{' '}
                  {master.control_mode}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Token delivery:</span>{' '}
                  {master.token_delivery}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Publish port:</span>{' '}
                  {master.publish_port}
                </span>
                <span>
                  <span className="font-medium text-gray-700">Return port:</span>{' '}
                  {master.ret_port}
                </span>
                {master.api_user && (
                  <span>
                    <span className="font-medium text-gray-700">API user:</span>{' '}
                    {master.api_user}
                  </span>
                )}
                {master.api_eauth && (
                  <span>
                    <span className="font-medium text-gray-700">eAuth:</span>{' '}
                    {master.api_eauth}
                  </span>
                )}
                <span>
                  <span className="font-medium text-gray-700">Last checked:</span>{' '}
                  {master.last_checked_at ? (
                    <span title={relativeTime(master.last_checked_at)}>
                      {formatIst(master.last_checked_at)}
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
                        <th className="px-5 py-2 text-left font-semibold text-gray-700">Check</th>
                        <th className="px-5 py-2 text-left font-semibold text-gray-700">Status</th>
                        <th className="px-5 py-2 text-left font-semibold text-gray-700">Detail</th>
                        <th className="px-5 py-2 text-right font-semibold text-gray-700">Latency</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {checks.map((chk, i) => (
                        <tr key={i} className="hover:bg-gray-50">
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
            </div>
          )
        })}
      </div>

      {/* Create modal */}
      {showCreate && (
        <MasterForm
          initial={EMPTY_FORM}
          title="Add Salt Master"
          submitLabel="Create"
          isLoading={createMutation.isPending}
          error={formError}
          onSubmit={handleCreate}
          onClose={() => { setShowCreate(false); setFormError(null) }}
        />
      )}

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

      {/* Delete confirm */}
      {deleteMaster && (
        <ConfirmDialog
          title={`Delete "${deleteMaster.name}"?`}
          message={`This will permanently remove the salt master "${deleteMaster.name}". Nodes assigned to it will need to be reassigned. This action cannot be undone.`}
          confirmLabel="Delete"
          destructive
          onConfirm={() => deleteMutation.mutate(deleteMaster.id)}
          onCancel={() => setDeleteMaster(null)}
        />
      )}
    </div>
  )
}
