import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../api/fleet'
import type { ImportRow, ImportValidateResponse } from '../api/fleet'
import { groupsApi } from '../api/groups'
import { useToastStore } from '../stores/toastStore'

// ─── Password input with show/hide toggle ──────────────────────────────────────
function PasswordInput({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder?: string
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-2.5 py-1.5 pr-9 text-sm border border-gray-300 rounded-lg focus:outline-none focus:border-brand-600"
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        aria-label={show ? 'Hide' : 'Show'}
      >
        {show
          ? <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" /></svg>
          : <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
        }
      </button>
    </div>
  )
}

// ─── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: ImportRow['status'] }) {
  if (status === 'new') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold"
        style={{ color: '#16A34A', backgroundColor: '#F0FDF4', border: '1px solid #BBF7D0' }}>
        ✓ New
      </span>
    )
  }
  if (status === 'duplicate') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold"
        style={{ color: '#D97706', backgroundColor: '#FFFBEB', border: '1px solid #FDE68A' }}>
        ⚠ Duplicate
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold"
      style={{ color: '#DC2626', backgroundColor: '#FEF2F2', border: '1px solid #FECACA' }}>
      ✗ Invalid
    </span>
  )
}

// ─── Preview table ─────────────────────────────────────────────────────────────
function PreviewTable({ result, loading }: { result: ImportValidateResponse | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-gray-400">
        Validating…
      </div>
    )
  }
  if (!result) return null

  const { rows, summary } = result

  return (
    <div className="mt-4 space-y-3">
      {/* Summary line */}
      <div className="flex items-center gap-4 text-sm font-medium">
        <span style={{ color: '#16A34A' }}>{summary.new} new</span>
        <span style={{ color: '#D97706' }}>{summary.duplicate} duplicate{summary.duplicate !== 1 ? 's' : ''}</span>
        <span style={{ color: '#DC2626' }}>{summary.invalid} blocked</span>
        <span className="text-gray-400 font-normal ml-auto">{summary.total} total</span>
      </div>

      {/* Table */}
      {rows.length > 0 && (
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <div style={{ maxHeight: '280px', overflowY: 'auto' }}>
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">Status</th>
                  <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">Minion ID</th>
                  <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">Hostname</th>
                  <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">IP</th>
                  <th className="text-left px-3 py-2 font-semibold text-gray-700">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((row, i) => (
                  <tr key={i} className={row.status === 'new' ? 'bg-white' : row.status === 'duplicate' ? 'bg-amber-50/50' : 'bg-red-50/50'}>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-900 whitespace-nowrap">{row.minion_id}</td>
                    <td className="px-3 py-2 text-gray-600 whitespace-nowrap">{row.hostname ?? '—'}</td>
                    <td className="px-3 py-2 text-gray-600 whitespace-nowrap">{row.ip ?? '—'}</td>
                    <td className="px-3 py-2 text-gray-500">{row.reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main modal ────────────────────────────────────────────────────────────────
export function ImportNodesModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  // Tab state
  const [tab, setTab] = useState<'paste' | 'csv' | 'salt'>('paste')

  // Paste tab
  const [pasteText, setPasteText] = useState('')
  const pasteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // CSV tab
  const [csvContent, setCsvContent] = useState<string | null>(null)
  const [csvFilename, setCsvFilename] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Validation result
  const [validateResult, setValidateResult] = useState<ImportValidateResponse | null>(null)
  const [validating, setValidating] = useState(false)
  const [validateError, setValidateError] = useState<string | null>(null)

  // Options
  const [groupId, setGroupId] = useState('')
  const [sshUsername, setSshUsername] = useState('')
  const [sshPassword, setSshPassword] = useState('')
  const [autoBootstrap, setAutoBootstrap] = useState(false)

  // Inline group creation
  const [showNewGroup, setShowNewGroup] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [creatingGroup, setCreatingGroup] = useState(false)

  // Groups
  const { data: groups } = useQuery({
    queryKey: ['groups-for-import'],
    queryFn: () => groupsApi.list({ per_page: 100 }),
    staleTime: 60_000,
  })

  // Cleanup timers on unmount
  useEffect(() => () => {
    if (pasteTimerRef.current) clearTimeout(pasteTimerRef.current)
  }, [])

  // ── Validate helpers ───────────────────────────────────────────────────────
  const runValidate = useCallback(async (body: Parameters<typeof fleetApi.importValidate>[0]) => {
    setValidating(true)
    setValidateError(null)
    try {
      const result = await fleetApi.importValidate(body)
      setValidateResult(result)
    } catch (e: any) {
      setValidateError(e.message ?? 'Validation failed')
      setValidateResult(null)
    } finally {
      setValidating(false)
    }
  }, [])

  // ── Paste tab: debounced validation ────────────────────────────────────────
  function onPasteChange(text: string) {
    setPasteText(text)
    if (pasteTimerRef.current) clearTimeout(pasteTimerRef.current)
    if (!text.trim()) {
      setValidateResult(null)
      return
    }
    pasteTimerRef.current = setTimeout(() => {
      runValidate({ source: 'paste', text })
    }, 400)
  }

  // ── CSV tab: file reader ───────────────────────────────────────────────────
  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setCsvFilename(file.name)
    const reader = new FileReader()
    reader.onload = (ev) => {
      const content = ev.target?.result as string
      setCsvContent(content)
      runValidate({ source: 'csv', csv_content: content })
    }
    reader.readAsText(file)
  }

  // ── Salt tab: validate on tab open ────────────────────────────────────────
  useEffect(() => {
    if (tab === 'salt') {
      setValidateResult(null)
      runValidate({ source: 'salt' })
    }
  }, [tab, runValidate])

  // Reset results when switching tabs
  function switchTab(newTab: 'paste' | 'csv' | 'salt') {
    if (newTab === tab) return
    setTab(newTab)
    setValidateResult(null)
    setValidateError(null)
    if (newTab !== 'salt') {
      // Salt kicks off its own validate via the useEffect
    }
  }

  // ── Group creation ─────────────────────────────────────────────────────────
  async function handleCreateGroup() {
    const name = newGroupName.trim()
    if (!name) return
    setCreatingGroup(true)
    try {
      const created = await groupsApi.create({ name, type: 'static' })
      qc.invalidateQueries({ queryKey: ['groups-for-import'] })
      setShowNewGroup(false)
      setNewGroupName('')
      setGroupId(created.id)
    } catch (e: any) {
      toast(e.message ?? 'Failed to create group', 'error')
    } finally {
      setCreatingGroup(false)
    }
  }

  // ── Commit mutation ────────────────────────────────────────────────────────
  const commitMutation = useMutation({
    mutationFn: () =>
      fleetApi.importCommit({
        rows: validateResult?.rows ?? [],
        group_id: groupId || undefined,
        ssh_username: sshUsername.trim() || undefined,
        ssh_password: sshPassword || undefined,
        auto_bootstrap: autoBootstrap,
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
      const msg = autoBootstrap && data.bootstrap_queued > 0
        ? `Imported ${data.created} node${data.created !== 1 ? 's' : ''} — ${data.bootstrap_queued} bootstrap${data.bootstrap_queued !== 1 ? 's' : ''} queued`
        : `Imported ${data.created} node${data.created !== 1 ? 's' : ''}`
      toast(msg)
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const summary = validateResult?.summary
  const canCommit = !!summary && summary.new > 0 && !commitMutation.isPending

  // ── Detected CSV columns (first line of CSV) ───────────────────────────────
  const csvColumns = csvContent
    ? csvContent.split('\n')[0]?.split(',').map(c => c.trim().replace(/^"|"$/g, '')).filter(Boolean)
    : []

  const tabs: { key: 'paste' | 'csv' | 'salt'; label: string }[] = [
    { key: 'paste', label: 'Paste List' },
    { key: 'csv',   label: 'CSV Upload' },
    { key: 'salt',  label: 'From Salt Master' },
  ]

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col" style={{ maxHeight: '90vh' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">Bulk Import Nodes</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 text-lg leading-none flex items-center justify-center"
          >
            ×
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

          {/* Tab bar */}
          <div className="flex gap-1 border-b border-gray-200">
            {tabs.map(t => (
              <button
                key={t.key}
                onClick={() => switchTab(t.key)}
                className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                  tab === t.key
                    ? 'text-brand-700 border-b-2 border-brand-600 bg-brand-50/50'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* ── Paste tab ─────────────────────────────────────────────────────── */}
          {tab === 'paste' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Node list
              </label>
              <textarea
                value={pasteText}
                onChange={e => onPasteChange(e.target.value)}
                rows={6}
                placeholder={"One per line:\n192.168.1.10\nmm-04,192.168.1.11\nminion-id,hostname,192.168.1.12"}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 font-mono focus:outline-none focus:border-brand-600 resize-y"
              />
              <p className="text-xs text-gray-400 mt-1">
                Each line: IP, or <code>minion-id,ip</code>, or <code>minion-id,hostname,ip</code>
              </p>
            </div>
          )}

          {/* ── CSV tab ──────────────────────────────────────────────────────── */}
          {tab === 'csv' && (
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  CSV file
                </label>
                <div
                  className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center cursor-pointer hover:border-brand-400 hover:bg-brand-50/30 transition-colors"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={onFileChange}
                  />
                  {csvFilename ? (
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-gray-900">{csvFilename}</p>
                      <p className="text-xs text-gray-400">Click to replace</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <svg className="mx-auto w-8 h-8 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p className="text-sm text-gray-500">Click to choose a CSV file</p>
                      <p className="text-xs text-gray-400">Columns auto-detected from header row</p>
                    </div>
                  )}
                </div>
              </div>
              {csvColumns.length > 0 && (
                <div className="rounded-lg bg-gray-50 border border-gray-200 px-3 py-2">
                  <p className="text-xs font-medium text-gray-500 mb-1">Detected columns:</p>
                  <div className="flex flex-wrap gap-1">
                    {csvColumns.map((col) => (
                      <span key={col} className="inline-block px-2 py-0.5 bg-white border border-gray-200 rounded text-xs text-gray-700 font-mono">
                        {col}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Salt tab ─────────────────────────────────────────────────────── */}
          {tab === 'salt' && (
            <div>
              <p className="text-sm text-gray-600">
                Querying Salt master for known minions not yet in the fleet…
              </p>
            </div>
          )}

          {/* Validation error */}
          {validateError && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3">
              <p className="text-sm text-red-700">{validateError}</p>
            </div>
          )}

          {/* Preview table */}
          <PreviewTable result={validateResult} loading={validating} />

          {/* ── Options block ─────────────────────────────────────────────────── */}
          <div className="border-t border-gray-100 pt-4 space-y-4">
            <h3 className="text-sm font-semibold text-gray-700">Import options</h3>

            {/* Group selector */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Assign to group <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <select
                value={groupId}
                onChange={e => {
                  if (e.target.value === '__new__') { setShowNewGroup(true); return }
                  setShowNewGroup(false)
                  setGroupId(e.target.value)
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 bg-white"
              >
                <option value="">No group</option>
                {(groups?.items ?? []).filter(g => g.type === 'static').map(g => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
                <option value="__new__">+ Create new group…</option>
              </select>
              {showNewGroup && (
                <div className="mt-2 flex gap-2 items-center">
                  <input
                    autoFocus
                    type="text"
                    value={newGroupName}
                    onChange={e => setNewGroupName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') { e.preventDefault(); handleCreateGroup() }
                      if (e.key === 'Escape') { setShowNewGroup(false); setNewGroupName('') }
                    }}
                    placeholder="Group name…"
                    className="flex-1 px-3 py-1.5 border border-brand-400 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 bg-white"
                  />
                  <button
                    type="button"
                    onClick={handleCreateGroup}
                    disabled={!newGroupName.trim() || creatingGroup}
                    className="px-3 py-1.5 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50"
                  >
                    {creatingGroup ? 'Creating…' : 'Create'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowNewGroup(false); setNewGroupName('') }}
                    className="px-3 py-1.5 border border-gray-300 text-gray-600 text-sm rounded-lg hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>

            {/* SSH credentials */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  SSH username <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  value={sshUsername}
                  onChange={e => setSshUsername(e.target.value)}
                  placeholder="admin"
                  className="w-full px-2.5 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:border-brand-600"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  SSH password <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <PasswordInput value={sshPassword} onChange={setSshPassword} placeholder="••••••••" />
              </div>
            </div>

            {/* Auto-bootstrap */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoBootstrap}
                onChange={e => setAutoBootstrap(e.target.checked)}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="text-sm font-medium text-gray-700">Auto-bootstrap after import</span>
            </label>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center gap-3">
          {summary && (
            <p className="text-sm text-gray-500 flex-1">
              Will create <span className="font-semibold" style={{ color: '#16A34A' }}>{summary.new}</span>,
              skip <span className="font-semibold" style={{ color: '#D97706' }}>{summary.duplicate}</span>{' '}
              duplicate{summary.duplicate !== 1 ? 's' : ''},
              {' '}<span className="font-semibold" style={{ color: '#DC2626' }}>{summary.invalid}</span> blocked
            </p>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            disabled={!canCommit}
            onClick={() => commitMutation.mutate()}
            className="px-5 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {commitMutation.isPending
              ? 'Importing…'
              : summary
                ? `Import ${summary.new} node${summary.new !== 1 ? 's' : ''}`
                : 'Import'
            }
          </button>
        </div>
      </div>
    </div>
  )
}
