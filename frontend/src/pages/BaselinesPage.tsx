import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { baselinesApi, type Baseline } from '../api/baselines'
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

const STARTER_STATE = {
  packages: [
    { name: 'salt', version: null },
  ],
  services: [
    { name: 'salt-minion', expected: 'running' },
  ],
}

// ─── Create modal ─────────────────────────────────────────────────────────────

function CreateBaselineModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [targetType, setTargetType] = useState<'global' | 'group' | 'node'>('global')
  const [targetId, setTargetId] = useState('')
  const [stateText, setStateText] = useState(JSON.stringify(STARTER_STATE, null, 2))
  const [jsonError, setJsonError] = useState<string | null>(null)

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

  const createMutation = useMutation({
    mutationFn: () => {
      let parsed: object
      try {
        parsed = JSON.parse(stateText)
      } catch {
        throw new Error('Invalid JSON in state definition')
      }
      return baselinesApi.create({
        name,
        description: description || undefined,
        target_type: targetType,
        target_id: targetId || undefined,
        state_json: parsed,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['baselines'] })
      toast('Baseline created')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function validateJson(text: string) {
    try { JSON.parse(text); setJsonError(null) }
    catch (e: unknown) { setJsonError(e instanceof Error ? e.message : 'Invalid JSON') }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">Create Baseline</h2>
          <button onClick={onClose} className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-lg">×</button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Baseline name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)}
              placeholder="macOS fleet standard"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description <span className="text-gray-400 font-normal">(optional)</span></label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="Expected state for production Mac Minis"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Applies to</label>
            <div className="flex gap-3">
              {(['global', 'group', 'node'] as const).map((t) => (
                <label key={t} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="radio" name="targetType" value={t}
                    checked={targetType === t}
                    onChange={() => { setTargetType(t); setTargetId('') }}
                    className="accent-brand-600" />
                  {TARGET_LABELS[t]}
                </label>
              ))}
            </div>
            {targetType !== 'global' && (
              <select required value={targetId} onChange={(e) => setTargetId(e.target.value)}
                className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600">
                <option value="">Select {targetType}…</option>
                {targetType === 'group'
                  ? groups?.items.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)
                  : nodes?.items.map((n) => <option key={n.id} value={n.id}>{n.hostname ?? n.minion_id}</option>)
                }
              </select>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">State definition <span className="text-gray-400 font-normal">(JSON)</span></label>
              {jsonError && <span className="text-xs text-red-600">{jsonError}</span>}
            </div>
            <p className="text-xs text-gray-500 mb-2">
              Define expected <code>packages</code> (name + optional version constraint) and <code>services</code> (name + expected state).
              Drift is scored by comparing each node's current SBOM against this definition.
            </p>
            <textarea
              rows={14}
              value={stateText}
              onChange={(e) => { setStateText(e.target.value); validateJson(e.target.value) }}
              spellCheck={false}
              className={`w-full px-3 py-2 border rounded-lg text-xs font-mono text-gray-900 focus:outline-none resize-none ${
                jsonError ? 'border-red-400 focus:border-red-500' : 'border-gray-300 focus:border-brand-600'
              }`}
            />
            <p className="text-xs text-gray-400 mt-1">
              Example: <code>{`{"packages":[{"name":"salt","version":">=3006.0"}],"services":[{"name":"salt-minion","expected":"running"}]}`}</code>
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200">
          <div className="flex gap-3">
            <button onClick={onClose}
              className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
              Cancel
            </button>
            <button
              disabled={!name || !!jsonError || createMutation.isPending || (targetType !== 'global' && !targetId)}
              onClick={() => createMutation.mutate()}
              className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
              {createMutation.isPending ? 'Creating…' : 'Create Baseline'}
            </button>
          </div>
        </div>
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
          className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
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
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Applies to</th>
                <th className="px-4 py-3">Version</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3 w-20"></th>
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
                  </td>
                  <td className="px-4 py-3 text-gray-500">v{b.version}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => setSelected(b)}
                      className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                      View
                    </button>
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
      {selected && <BaselineDetail baseline={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
