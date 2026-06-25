import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { baselinesApi, type Baseline, type CaptureResult } from '../api/baselines'
import { groupsApi } from '../api/groups'
import { fleetApi } from '../api/fleet'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { formatDistanceToNow } from 'date-fns'

const TARGET_LABELS: Record<string, string> = {
  global: 'All nodes',
  group:  'Group',
  node:   'Node',
}

// ─── Baseline form types ──────────────────────────────────────────────────────

interface PkgRow { _key: string; name: string; version: string; enforce: boolean }
interface SvcRow { _key: string; name: string; state: 'running' | 'stopped' }

function newKey() { return crypto.randomUUID() }

function buildStateJson(required: PkgRow[], forbidden: PkgRow[], services: SvcRow[]) {
  return {
    packages: {
      required: required
        .filter(p => p.name.trim())
        .map(p => ({ name: p.name.trim(), ...(p.enforce && p.version.trim() ? { version: `>=${p.version.trim()}` } : {}) })),
      forbidden: forbidden
        .filter(p => p.name.trim())
        .map(p => ({ name: p.name.trim() })),
    },
    services: {
      required_running: services.filter(s => s.name.trim() && s.state === 'running').map(s => s.name.trim()),
      required_stopped: services.filter(s => s.name.trim() && s.state === 'stopped').map(s => s.name.trim()),
    },
  }
}

function parseStateJson(stateJson: Record<string, unknown>): { required: PkgRow[], forbidden: PkgRow[], services: SvcRow[] } {
  const pkgs = (stateJson?.packages ?? {}) as Record<string, { name?: string; version?: string }[]>
  const svc = (stateJson?.services ?? {}) as { required_running?: string[]; required_stopped?: string[] }
  const required = (pkgs.required ?? []).map((p: { name?: string; version?: string }) => ({
    _key: newKey(),
    name: p.name ?? '',
    version: (p.version ?? '').replace('>=', ''),
    enforce: !!(p.version),
  }))
  const forbidden = (pkgs.forbidden ?? []).map((p: { name?: string }) => ({
    _key: newKey(),
    name: p.name ?? '',
    version: '',
    enforce: false,
  }))
  const svcRunning = (svc.required_running ?? []).map((s: string) => ({ _key: newKey(), name: s, state: 'running' as const }))
  const svcStopped = (svc.required_stopped ?? []).map((s: string) => ({ _key: newKey(), name: s, state: 'stopped' as const }))
  return { required, forbidden, services: [...svcRunning, ...svcStopped] }
}

// ─── Capture mode ─────────────────────────────────────────────────────────────

function CaptureMode({
  required, setRequired, forbidden, services,
}: {
  required: PkgRow[]
  setRequired: (rows: PkgRow[]) => void
  forbidden: PkgRow[]
  services: SvcRow[]
}) {
  const { data: nodes } = useQuery({
    queryKey: ['nodes-for-capture'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    staleTime: 30_000,
  })
  const [nodeId, setNodeId] = useState('')
  const [captured, setCaptured] = useState<CaptureResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function doCapture() {
    if (!nodeId) return
    setLoading(true); setErr(null)
    try {
      const result = await baselinesApi.capture(nodeId)
      setCaptured(result)
      // Pre-populate required packages (all selected, no version enforcement)
      setRequired(result.packages.map(p => ({ _key: newKey(), name: p.name, version: p.version ?? '', enforce: false })))
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to capture node state')
    } finally {
      setLoading(false)
    }
  }

  const onlineNodes = nodes?.items.filter(n => n.status === 'online') ?? []

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <select
          value={nodeId}
          onChange={e => { setNodeId(e.target.value); setCaptured(null) }}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:border-brand-600"
        >
          <option value="">Select a live node…</option>
          {onlineNodes.map(n => (
            <option key={n.id} value={n.id}>
              {n.hostname ?? n.minion_id}
            </option>
          ))}
        </select>
        <button
          onClick={doCapture}
          disabled={!nodeId || loading}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 whitespace-nowrap"
        >
          {loading ? 'Loading…' : '📸 Snapshot'}
        </button>
      </div>

      {err && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3">{err}</p>}

      {captured && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700">
              {captured.package_count} packages found on <span className="font-semibold">{captured.hostname ?? captured.minion_id}</span>
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setRequired(required.map(r => ({ ...r, enforce: true })))}
                className="text-xs text-brand-600 hover:text-brand-700"
              >Check all versions</button>
              <span className="text-gray-300">·</span>
              <button
                onClick={() => setRequired(required.map(r => ({ ...r, enforce: false })))}
                className="text-xs text-gray-500 hover:text-gray-700"
              >Presence only</button>
            </div>
          </div>

          <div className="border border-gray-200 rounded-xl overflow-hidden">
            <div className="max-h-64 overflow-y-auto divide-y divide-gray-100">
              {required.map((row, i) => (
                <div key={captured.packages[i]?.name ?? i} className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50">
                  <input
                    type="checkbox"
                    checked={row.name !== ''}
                    onChange={e => {
                      if (!e.target.checked) {
                        setRequired(required.map((r, j) => j === i ? { ...r, name: '' } : r))
                      } else {
                        setRequired(required.map((r, j) => j === i ? { ...r, name: captured.packages[i].name } : r))
                      }
                    }}
                    className="accent-brand-600 shrink-0"
                  />
                  <span className="text-sm font-mono text-gray-800 flex-1 truncate">
                    {captured.packages[i].name}
                  </span>
                  <span className="text-xs text-gray-400 font-mono w-20 text-right shrink-0">
                    {captured.packages[i].version ?? '—'}
                  </span>
                  <label className="flex items-center gap-1.5 shrink-0">
                    <input
                      type="checkbox"
                      checked={row.enforce}
                      disabled={!row.name}
                      onChange={e => setRequired(required.map((r, j) => j === i ? { ...r, enforce: e.target.checked } : r))}
                      className="accent-brand-600"
                    />
                    <span className="text-xs text-gray-500">pin version</span>
                  </label>
                </div>
              ))}
            </div>
          </div>
          <p className="text-xs text-gray-400">
            Unchecked packages are ignored. "Pin version" enforces <code>&gt;=version</code> in drift checks.
          </p>
        </div>
      )}

      {!captured && !loading && !err && (
        <div className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center text-gray-400">
          <p className="text-2xl mb-2">📸</p>
          <p className="text-sm">Select a node and click Snapshot to load its installed packages</p>
        </div>
      )}

      {/* Suppress unused-variable warnings — forbidden/services passed for summary badge */}
      {forbidden.length + services.length > 1_000_000 && null}
    </div>
  )
}

// ─── Manual mode ──────────────────────────────────────────────────────────────

function ManualMode({
  required, setRequired,
  forbidden, setForbidden,
  services, setServices,
}: {
  required: PkgRow[]; setRequired: (r: PkgRow[]) => void
  forbidden: PkgRow[]; setForbidden: (r: PkgRow[]) => void
  services: SvcRow[]; setServices: (s: SvcRow[]) => void
}) {
  const inputClass = 'px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:border-brand-600'
  const [focusedPkgIdx, setFocusedPkgIdx] = useState<number | null>(null)

  const { data: suggestions = [] } = useQuery({
    queryKey: ['common-packages'],
    queryFn: () => api.get<Array<{name: string; version: string; node_count: number}>>('/api/v1/baselines/common-packages'),
    staleTime: 5 * 60_000,
  })

  return (
    <div className="space-y-6">
      {/* Required packages */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-semibold text-gray-700">Required packages</label>
          <span className="text-xs text-gray-400">must be installed for zero drift</span>
        </div>
        <div className="space-y-2">
          {required.map((row, i) => {
            const matches = row.name.trim().length > 0
              ? suggestions.filter(s => s.name.toLowerCase().startsWith(row.name.toLowerCase()) && s.name !== row.name).slice(0, 6)
              : []
            const showDropdown = focusedPkgIdx === i && matches.length > 0
            return (
              <div key={row._key} className="relative">
                <div className="flex gap-2 items-center">
                  <input
                    value={row.name}
                    onChange={e => setRequired(required.map((r, j) => j === i ? { ...r, name: e.target.value } : r))}
                    onFocus={() => setFocusedPkgIdx(i)}
                    onBlur={() => setTimeout(() => setFocusedPkgIdx(null), 150)}
                    placeholder="package name"
                    className={`${inputClass} flex-1`}
                  />
                  <span className="text-gray-400 text-sm">≥</span>
                  <input
                    value={row.version}
                    onChange={e => setRequired(required.map((r, j) => j === i ? { ...r, version: e.target.value } : r))}
                    placeholder="version (optional)"
                    className={`${inputClass} w-36`}
                  />
                  <button
                    onClick={() => setRequired(required.filter((_, j) => j !== i))}
                    className="text-gray-400 hover:text-red-500 text-lg leading-none shrink-0"
                  >×</button>
                </div>
                {showDropdown && (
                  <div className="absolute z-10 left-0 top-full mt-0.5 w-80 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">
                    {matches.map(s => (
                      <button
                        key={s.name}
                        onMouseDown={() => {
                          setRequired(required.map((r, j) => j === i ? { ...r, name: s.name, version: s.version || r.version } : r))
                          setFocusedPkgIdx(null)
                        }}
                        className="flex items-center justify-between w-full px-3 py-1.5 hover:bg-brand-50 text-left"
                      >
                        <span className="text-sm font-mono text-gray-800">{s.name}</span>
                        <span className="text-xs text-gray-400 ml-2 shrink-0">{s.version} · {s.node_count} nodes</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <button
          onClick={() => setRequired([...required, { _key: newKey(), name: '', version: '', enforce: false }])}
          className="mt-2 text-sm text-brand-600 hover:text-brand-700 font-medium"
        >+ Add required package</button>
      </div>

      {/* Forbidden packages */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-semibold text-gray-700">Forbidden packages</label>
          <span className="text-xs text-gray-400">must NOT be installed</span>
        </div>
        <div className="space-y-2">
          {forbidden.map((row, i) => (
            <div key={row._key} className="flex gap-2 items-center">
              <input
                value={row.name}
                onChange={e => setForbidden(forbidden.map((r, j) => j === i ? { ...r, name: e.target.value } : r))}
                placeholder="package name"
                className={`${inputClass} flex-1`}
              />
              <button
                onClick={() => setForbidden(forbidden.filter((_, j) => j !== i))}
                className="text-gray-400 hover:text-red-500 text-lg leading-none"
              >×</button>
            </div>
          ))}
        </div>
        <button
          onClick={() => setForbidden([...forbidden, { _key: newKey(), name: '', version: '', enforce: false }])}
          className="mt-2 text-sm text-brand-600 hover:text-brand-700 font-medium"
        >+ Add forbidden package</button>
      </div>

      {/* Services */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-semibold text-gray-700">Services</label>
          <span className="text-xs text-gray-400">expected running/stopped state</span>
        </div>
        <div className="space-y-2">
          {services.map((row, i) => (
            <div key={row._key} className="flex gap-2 items-center">
              <input
                value={row.name}
                onChange={e => setServices(services.map((s, j) => j === i ? { ...s, name: e.target.value } : s))}
                placeholder="service name"
                className={`${inputClass} flex-1`}
              />
              <div className="flex rounded-lg border border-gray-300 overflow-hidden text-xs">
                <button
                  onClick={() => setServices(services.map((s, j) => j === i ? { ...s, state: 'running' } : s))}
                  className={`px-3 py-1.5 font-medium transition-colors ${row.state === 'running' ? 'bg-emerald-600 text-white' : 'text-gray-500 hover:bg-gray-50'}`}
                >● running</button>
                <button
                  onClick={() => setServices(services.map((s, j) => j === i ? { ...s, state: 'stopped' } : s))}
                  className={`px-3 py-1.5 font-medium transition-colors ${row.state === 'stopped' ? 'bg-red-500 text-white' : 'text-gray-500 hover:bg-gray-50'}`}
                >○ stopped</button>
              </div>
              <button
                onClick={() => setServices(services.filter((_, j) => j !== i))}
                className="text-gray-400 hover:text-red-500 text-lg leading-none"
              >×</button>
            </div>
          ))}
        </div>
        <button
          onClick={() => setServices([...services, { _key: newKey(), name: '', state: 'running' }])}
          className="mt-2 text-sm text-brand-600 hover:text-brand-700 font-medium"
        >+ Add service</button>
      </div>
    </div>
  )
}

// ─── Create/Edit modal ─────────────────────────────────────────────────────────

function CreateBaselineModal({ onClose, existing }: { onClose: () => void; existing?: Baseline }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const isEdit = !!existing

  // Mode: when editing, skip directly to manual
  const [mode, setMode] = useState<'choose' | 'capture' | 'manual'>(isEdit ? 'manual' : 'choose')

  // Shared state — pre-fill from existing if editing
  const [name, setName] = useState(existing?.name ?? '')
  const [description, setDescription] = useState(existing?.description ?? '')
  const [targetType, setTargetType] = useState<'global' | 'group' | 'node'>(
    (existing?.target_type as 'global' | 'group' | 'node') ?? 'global'
  )
  const [targetId, setTargetId] = useState(existing?.target_id ?? '')
  // os_family: 'any' = OS-agnostic (omit/clear); else send the canonical
  // family label. The picker exists primarily to scope macOS-only rules
  // (e.g. com.apple.screensharing in required_stopped) so they don't
  // generate false drift on Linux nodes from a global baseline.
  const [osFamily, setOsFamily] = useState<'any' | 'Darwin' | 'Linux' | 'FreeBSD' | 'Windows'>(
    (existing?.os_family as 'Darwin' | 'Linux' | 'FreeBSD' | 'Windows' | null) ?? 'any'
  )

  // Package/service state — parse from existing state_json if editing
  const parsedInitial = existing ? parseStateJson((existing as { state_json?: Record<string, unknown> }).state_json ?? {}) : null
  const [required, setRequired] = useState<PkgRow[]>(parsedInitial?.required ?? [])
  const [forbidden, setForbidden] = useState<PkgRow[]>(parsedInitial?.forbidden ?? [])
  const [services, setServices] = useState<SvcRow[]>(parsedInitial?.services ?? [])

  const { data: groups } = useQuery({
    queryKey: ['groups-for-baseline'],
    queryFn: () => groupsApi.list({ per_page: 200 }),
    enabled: targetType === 'group',
    staleTime: 60_000,
  })
  const { data: nodes } = useQuery({
    queryKey: ['nodes-for-baseline'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    enabled: targetType === 'node',
    staleTime: 60_000,
  })

  const stateJson = buildStateJson(required, forbidden, services)
  const hasContent = required.some(r => r.name.trim()) || forbidden.some(f => f.name.trim()) || services.some(s => s.name.trim())

  const createMutation = useMutation({
    mutationFn: () => isEdit
      ? baselinesApi.update(existing!.id, {
          name,
          description: description || undefined,
          state_json: stateJson,
          // Empty string clears the column (becomes OS-agnostic). The
          // backend distinguishes `""` from `undefined` so an unchanged
          // os_family is preserved when other fields are edited.
          os_family: osFamily === 'any' ? '' : osFamily,
        })
      : baselinesApi.create({
          name,
          description: description || undefined,
          target_type: targetType,
          target_id: targetId || undefined,
          state_json: stateJson,
          os_family: osFamily === 'any' ? null : osFamily,
        }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['baselines'] })
      toast(isEdit ? 'Baseline updated' : 'Baseline created')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const canCreate = name.trim() && hasContent && (targetType === 'global' || targetId)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-3">
            {mode !== 'choose' && (
              <button onClick={() => setMode('choose')} className="text-gray-400 hover:text-gray-600 text-sm">← Back</button>
            )}
            <h2 className="text-lg font-bold text-gray-900">
              {isEdit ? `Edit Baseline` : mode === 'choose' ? 'New Baseline' : mode === 'capture' ? '📸 Capture from Node' : '✏️ Build Manually'}
            </h2>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 text-lg">×</button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {mode === 'choose' ? (
            <div className="space-y-4">
              <p className="text-sm text-gray-500">How do you want to define the expected state?</p>
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setMode('capture')}
                  className="group border-2 border-gray-200 hover:border-brand-500 rounded-xl p-5 text-left transition-colors"
                >
                  <div className="text-3xl mb-3">📸</div>
                  <p className="font-semibold text-gray-900 group-hover:text-brand-700">Capture from node</p>
                  <p className="text-sm text-gray-500 mt-1">
                    Snapshot what's actually installed on a live node. One click — perfect for "gold image" workflows.
                  </p>
                </button>
                <button
                  onClick={() => setMode('manual')}
                  className="group border-2 border-gray-200 hover:border-brand-500 rounded-xl p-5 text-left transition-colors"
                >
                  <div className="text-3xl mb-3">✏️</div>
                  <p className="font-semibold text-gray-900 group-hover:text-brand-700">Build manually</p>
                  <p className="text-sm text-gray-500 mt-1">
                    Specify required packages, forbidden packages, and expected service states one by one.
                  </p>
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Mode-specific content */}
              {mode === 'capture' ? (
                <CaptureMode required={required} setRequired={setRequired} forbidden={forbidden} services={services} />
              ) : (
                <ManualMode
                  required={required} setRequired={setRequired}
                  forbidden={forbidden} setForbidden={setForbidden}
                  services={services} setServices={setServices}
                />
              )}

              {/* Summary badge when content exists */}
              {hasContent && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex gap-4 text-xs text-gray-600">
                  <span>📦 {required.filter(r => r.name.trim()).length} required</span>
                  {forbidden.filter(f => f.name.trim()).length > 0 && (
                    <span>🚫 {forbidden.filter(f => f.name.trim()).length} forbidden</span>
                  )}
                  {services.filter(s => s.name.trim()).length > 0 && (
                    <span>⚙️ {services.filter(s => s.name.trim()).length} services</span>
                  )}
                </div>
              )}

              {/* Name + target (always visible in non-choose mode) */}
              <div className="border-t border-gray-100 pt-5 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Baseline name</label>
                  <input
                    value={name}
                    onChange={e => setName(e.target.value)}
                    placeholder="macOS production standard"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:border-brand-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description <span className="text-gray-400 font-normal">(optional)</span></label>
                  <input
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    placeholder="Expected state for production Mac Minis"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:border-brand-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Applies to</label>
                  <div className="flex gap-4">
                    {(['global', 'group', 'node'] as const).map(t => (
                      <label key={t} className="flex items-center gap-2 text-sm cursor-pointer">
                        <input type="radio" name="targetType" value={t}
                          checked={targetType === t}
                          onChange={() => { setTargetType(t); setTargetId('') }}
                          className="accent-brand-600" />
                        {t === 'global' ? 'All nodes' : t === 'group' ? 'Group' : 'Node'}
                      </label>
                    ))}
                  </div>
                  {targetType !== 'global' && (
                    <select value={targetId} onChange={e => setTargetId(e.target.value)}
                      className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:border-brand-600">
                      <option value="">Select {targetType}…</option>
                      {targetType === 'group'
                        ? groups?.items.map(g => <option key={g.id} value={g.id}>{g.name}</option>)
                        : nodes?.items.map(n => <option key={n.id} value={n.id}>{n.hostname ?? n.minion_id}</option>)
                      }
                    </select>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    OS family <span className="text-gray-400 font-normal">(optional)</span>
                  </label>
                  <select
                    value={osFamily ?? 'any'}
                    onChange={e => setOsFamily(e.target.value as typeof osFamily)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-hidden focus:border-brand-600"
                  >
                    <option value="any">Any OS (apply to all)</option>
                    <option value="Darwin">Darwin (macOS)</option>
                    <option value="Linux">Linux</option>
                    <option value="FreeBSD">FreeBSD</option>
                    <option value="Windows">Windows</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    OS-specific baselines take priority over OS-agnostic ones at the same target tier.
                    A Darwin baseline only applies to macOS nodes.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {mode !== 'choose' && (
          <div className="px-6 py-4 border-t border-gray-200 flex gap-3">
            <button onClick={onClose}
              className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
              Cancel
            </button>
            <button
              disabled={!canCreate || createMutation.isPending}
              onClick={() => createMutation.mutate()}
              className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
            >
              {createMutation.isPending ? (isEdit ? 'Saving…' : 'Creating…') : (isEdit ? 'Save Changes' : 'Create Baseline')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Baseline detail panel ─────────────────────────────────────────────────────

function BaselineDetail({ baseline, onClose }: { baseline: Baseline; onClose: () => void }) {
  const raw = JSON.stringify((baseline as unknown as Record<string, unknown>)['state_json'] ?? {}, null, 2)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-bold text-gray-900">{baseline.name}</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              {TARGET_LABELS[baseline.target_type]} · v{baseline.version} · created {formatDistanceToNow(new Date(baseline.created_at), { addSuffix: true })}
            </p>
          </div>
          <button onClick={onClose} className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 text-lg">×</button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {baseline.description && (
            <p className="text-sm text-gray-600">{baseline.description}</p>
          )}
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">State Definition</p>
            <pre className="text-xs font-mono bg-gray-900 text-gray-100 rounded-lg p-4 overflow-auto max-h-80 whitespace-pre-wrap">
              {raw}
            </pre>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-200">
          <button onClick={onClose}
            className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function BaselinesPage() {
  const [page, setPage] = useState(1)
  const [showCreate, setShowCreate] = useState(false)
  const [selected, setSelected] = useState<Baseline | null>(null)
  const [editTarget, setEditTarget] = useState<Baseline | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['baselines', page],
    queryFn: () => baselinesApi.list({ page, per_page: 25 }),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Baselines</h1>
          <p className="text-gray-500 mt-1 text-sm">
            Define the expected state for your fleet. Drift is calculated by comparing each node's
            current SBOM against the baseline assigned to it.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-xs"
        >
          + New Baseline
        </button>
      </div>

      {/* How it works */}
      <div className="bg-brand-50 border border-brand-200 rounded-xl p-4 text-sm text-brand-800 space-y-1">
        <p className="font-semibold">How drift is calculated</p>
        <p>
          When a Salt minion sends its SBOM (package list), kri compares it against the baseline
          assigned to that node. Missing packages, version mismatches, and stopped services each
          add to the drift score. Nodes with no assigned baseline score 0 (no drift).
        </p>
        <p className="text-xs text-brand-600 mt-1">
          Assign a baseline by targeting <strong>All nodes</strong> (global), a <strong>Group</strong>, or a specific <strong>Node</strong>.
          The most specific target wins — node &gt; group &gt; global.
        </p>
      </div>

      {isLoading ? (
        <Skeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Failed to load baselines" retry={refetch} />
      ) : data?.items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center space-y-3">
          <p className="text-gray-400 text-sm">No baselines defined yet.</p>
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700">
            Create your first baseline
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">Applies to</th>
                <th scope="col" className="px-4 py-3">Version</th>
                <th scope="col" className="px-4 py-3">Created</th>
                <th scope="col" className="px-4 py-3 w-28"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items.map((b) => (
                <tr key={b.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900">{b.name}</p>
                    {b.description && <p className="text-xs text-gray-400 mt-0.5">{b.description}</p>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
                      b.target_type === 'global' ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : b.target_type === 'group' ? 'bg-purple-50 text-purple-700 border-purple-200'
                      : 'bg-brand-50 text-brand-700 border-brand-200'
                    }`}>
                      {TARGET_LABELS[b.target_type]}
                    </span>
                    {b.os_family && (
                      <span
                        className="ml-1.5 text-xs px-2 py-0.5 rounded font-medium border bg-slate-50 text-slate-700 border-slate-200"
                        title={`Only applies to ${b.os_family} nodes`}
                      >
                        {b.os_family}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500">v{b.version}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button onClick={() => setEditTarget(b)}
                        className="text-xs text-amber-600 hover:text-amber-700 font-medium">
                        Edit
                      </button>
                      <button onClick={() => setSelected(b)}
                        className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                        View
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && (
            <Pagination page={page} total={data.total} perPage={data.per_page} onPage={setPage} />
          )}
        </div>
      )}

      {showCreate && <CreateBaselineModal onClose={() => setShowCreate(false)} />}
      {editTarget && <CreateBaselineModal existing={editTarget} onClose={() => setEditTarget(null)} />}
      {selected && <BaselineDetail baseline={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
