import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { saltOpsApi, type SaltState } from '../api/saltOps'
import { fleetApi } from '../api/fleet'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { useToastStore } from '../stores/toastStore'

interface PillarOverride {
  key: string
  value: string
}

function parseStateTree(states: SaltState[]): Record<string, SaltState[]> {
  const tree: Record<string, SaltState[]> = {}
  for (const s of states) {
    const parts = s.path.split('/')
    const folder = parts.length > 1 ? parts[0] : ''
    if (!tree[folder]) tree[folder] = []
    tree[folder].push(s)
  }
  return tree
}

function renderSaltOutput(stdout: string): { minion: string; states: Array<{ id: string; result: boolean; changes: boolean; comment: string }> }[] {
  try {
    const parsed = JSON.parse(stdout)
    return Object.entries(parsed).map(([minion, stateMap]) => {
      const stateEntries = Object.entries(stateMap as Record<string, { result: boolean; changes: Record<string, unknown>; comment: string }>)
      return {
        minion,
        states: stateEntries.map(([id, v]) => ({
          id,
          result: v.result,
          changes: Object.keys(v.changes ?? {}).length > 0,
          comment: v.comment ?? '',
        })),
      }
    })
  } catch {
    return []
  }
}

export function SaltOpsPage() {
  const toast = useToastStore((s) => s.add)

  const [selectedState, setSelectedState] = useState<SaltState | null>(null)
  const [selectedMinions, setSelectedMinions] = useState<Set<string>>(new Set())
  const [pillarOverrides, setPillarOverrides] = useState<PillarOverride[]>([{ key: '', value: '' }])
  const [showPillarOverrides, setShowPillarOverrides] = useState(false)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskOutput, setTaskOutput] = useState<{ status: string; stdout?: string; stderr?: string; reason?: string } | null>(null)
  const [applying, setApplying] = useState(false)

  const { data: statesData, isLoading: statesLoading } = useQuery({
    queryKey: ['salt-states'],
    queryFn: saltOpsApi.listStates,
    staleTime: 60_000,
  })

  const { data: nodesData, isLoading: nodesLoading } = useQuery({
    queryKey: ['nodes-salt'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    staleTime: 60_000,
  })

  const { data: taskStatus } = useQuery({
    queryKey: ['salt-task', taskId],
    queryFn: () => api.get<{ task_id: string; state: string; result?: { status: string; stdout?: string; stderr?: string; reason?: string } }>(
      `/api/v1/ansible/tasks/${taskId}`
    ),
    enabled: !!taskId && applying,
    refetchInterval: (q) => {
      const state = q.state.data?.state
      if (state === 'SUCCESS' || state === 'FAILURE') {
        setApplying(false)
        if (q.state.data?.result) setTaskOutput(q.state.data.result)
        return false
      }
      return 2000
    },
  })

  const states = statesData?.states ?? []
  const nodes = nodesData?.items ?? []
  const stateTree = parseStateTree(states)
  const folders = Object.keys(stateTree).sort()

  const allMinions = nodes.map((n) => n.minion_id ?? n.id)
  const allSelected = allMinions.length > 0 && allMinions.every((m) => selectedMinions.has(m))

  function toggleFolder(folder: string) {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      if (next.has(folder)) next.delete(folder)
      else next.add(folder)
      return next
    })
  }

  function toggleMinion(minionId: string) {
    setSelectedMinions((prev) => {
      const next = new Set(prev)
      if (next.has(minionId)) next.delete(minionId)
      else next.add(minionId)
      return next
    })
  }

  function toggleAll() {
    if (allSelected) {
      setSelectedMinions(new Set())
    } else {
      setSelectedMinions(new Set(allMinions))
    }
  }

  function getPillarDict(): Record<string, string> | undefined {
    const entries = pillarOverrides.filter((p) => p.key.trim())
    if (!entries.length) return undefined
    return Object.fromEntries(entries.map((p) => [p.key.trim(), p.value]))
  }

  async function applyState() {
    if (!selectedState || selectedMinions.size === 0) return
    setApplying(true)
    setTaskOutput(null)
    setTaskId(null)
    try {
      const resp = await saltOpsApi.apply(
        selectedState.name,
        Array.from(selectedMinions),
        getPillarDict(),
      )
      setTaskId(resp.task_id)
      toast(`State "${selectedState.display}" queued`)
    } catch (e: unknown) {
      setApplying(false)
      toast(e instanceof Error ? e.message : 'Apply failed', 'error')
    }
  }

  const parsedOutput = taskOutput?.stdout ? renderSaltOutput(taskOutput.stdout) : []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Salt Ops</h1>
        <p className="text-sm text-gray-500 mt-1">Browse and apply Salt states to fleet nodes.</p>
      </div>

      <div className="flex gap-6 items-start">
        {/* Left panel — state browser */}
        <div className="w-1/3 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex-shrink-0">
          <div className="px-4 py-3 border-b border-gray-200">
            <p className="text-sm font-semibold text-gray-700">States</p>
            <p className="text-xs text-gray-400 mt-0.5">{statesData?.states_dir ?? '/srv/salt/states'}</p>
          </div>
          {statesLoading ? (
            <Skeleton rows={4} />
          ) : states.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">No .sls files found.</div>
          ) : (
            <ul className="py-2">
              {folders.map((folder) => {
                const folderStates = stateTree[folder]
                const isOpen = expandedFolders.has(folder)
                if (!folder) {
                  // Root-level states
                  return folderStates.map((s) => (
                    <li key={s.name}>
                      <button
                        onClick={() => setSelectedState(s)}
                        className={`w-full text-left px-4 py-2 text-sm font-mono transition-colors ${
                          selectedState?.name === s.name
                            ? 'bg-brand-50 text-brand-700 border-l-2 border-brand-600'
                            : 'text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        {s.display}
                      </button>
                    </li>
                  ))
                }
                return (
                  <li key={folder}>
                    <button
                      onClick={() => toggleFolder(folder)}
                      className="w-full text-left px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                    >
                      <span className="text-xs text-gray-400">{isOpen ? '▾' : '▸'}</span>
                      <span className="font-mono">{folder}</span>
                      <span className="ml-auto text-xs text-gray-400">{folderStates.length}</span>
                    </button>
                    {isOpen && (
                      <ul>
                        {folderStates.map((s) => (
                          <li key={s.name}>
                            <button
                              onClick={() => setSelectedState(s)}
                              className={`w-full text-left pl-8 pr-4 py-1.5 text-sm font-mono transition-colors ${
                                selectedState?.name === s.name
                                  ? 'bg-brand-50 text-brand-700 border-l-2 border-brand-600'
                                  : 'text-gray-600 hover:bg-gray-50'
                              }`}
                            >
                              {s.display.includes('.') ? s.display.split('.').slice(1).join('.') : s.display}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {/* Right panel */}
        <div className="flex-1 space-y-4">
          {!selectedState ? (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center text-gray-400">
              <p className="text-base">Select a state from the left panel to apply it.</p>
            </div>
          ) : (
            <>
              {/* State header */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-4 py-3 flex items-center gap-3">
                <span className="text-lg text-gray-400">⚡</span>
                <div>
                  <p className="font-mono font-semibold text-gray-900">{selectedState.display}</p>
                  <p className="text-xs text-gray-400 font-mono">{selectedState.path}</p>
                </div>
              </div>

              {/* Node selector */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="accent-brand-600"
                    />
                    Select all
                  </label>
                  <span className="ml-auto text-xs text-gray-400">
                    {selectedMinions.size} of {nodes.length} selected
                  </span>
                </div>
                {nodesLoading ? (
                  <Skeleton rows={3} />
                ) : nodes.length === 0 ? (
                  <div className="px-4 py-6 text-center text-gray-400 text-sm">No nodes registered.</div>
                ) : (
                  <ul className="divide-y divide-gray-100 max-h-64 overflow-y-auto">
                    {nodes.map((n) => {
                      const minionId = n.minion_id ?? n.id
                      const checked = selectedMinions.has(minionId)
                      return (
                        <li key={n.id}>
                          <label className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleMinion(minionId)}
                              className="accent-brand-600"
                            />
                            <span className="font-medium text-sm text-gray-900 flex-1">
                              {n.hostname ?? n.minion_id}
                            </span>
                            <StatusBadge status={n.status} />
                            <DriftBadge score={n.drift_score} />
                          </label>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>

              {/* Pillar overrides (advanced, collapsed) */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                <button
                  onClick={() => setShowPillarOverrides((v) => !v)}
                  className="w-full px-4 py-3 flex items-center gap-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  <span className="text-xs text-gray-400">{showPillarOverrides ? '▾' : '▸'}</span>
                  Pillar Overrides (advanced)
                  <span className="ml-auto text-xs text-gray-400">
                    {pillarOverrides.filter((p) => p.key.trim()).length} set
                  </span>
                </button>
                {showPillarOverrides && (
                  <div className="px-4 pb-4 space-y-2 border-t border-gray-100">
                    <p className="text-xs text-gray-400 pt-3">
                      Override pillar values at runtime. These are merged on top of stored secrets.
                    </p>
                    {pillarOverrides.map((p, i) => (
                      <div key={i} className="flex gap-2">
                        <input
                          value={p.key}
                          onChange={(e) => {
                            const next = [...pillarOverrides]
                            next[i] = { ...next[i], key: e.target.value }
                            setPillarOverrides(next)
                          }}
                          placeholder="key"
                          className="flex-1 text-sm border border-gray-300 rounded px-2 py-1 font-mono focus:outline-none focus:ring-2 focus:ring-brand-400"
                        />
                        <input
                          value={p.value}
                          onChange={(e) => {
                            const next = [...pillarOverrides]
                            next[i] = { ...next[i], value: e.target.value }
                            setPillarOverrides(next)
                          }}
                          placeholder="value"
                          className="flex-1 text-sm border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-brand-400"
                        />
                        <button
                          type="button"
                          onClick={() => setPillarOverrides(pillarOverrides.filter((_, j) => j !== i))}
                          className="text-gray-400 hover:text-red-500 px-1"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => setPillarOverrides([...pillarOverrides, { key: '', value: '' }])}
                      className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                    >
                      + Add override
                    </button>
                  </div>
                )}
              </div>

              {/* Apply button */}
              <div className="flex justify-end">
                <button
                  onClick={applyState}
                  disabled={applying || selectedMinions.size === 0}
                  className="px-6 py-2.5 bg-brand-600 text-white text-sm font-semibold rounded-lg hover:bg-brand-700 disabled:opacity-50 shadow-sm flex items-center gap-2"
                >
                  {applying && (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  )}
                  {applying ? 'Applying…' : `⚡ Apply State`}
                </button>
              </div>

              {/* Task status / output */}
              {(applying || taskOutput) && (
                <div className={`rounded-xl border overflow-hidden ${
                  taskOutput?.status === 'ok' ? 'border-emerald-200' :
                  taskOutput?.status === 'error' ? 'border-red-200' :
                  'border-brand-200'
                }`}>
                  <div className={`px-4 py-3 flex items-center gap-2 text-sm font-medium ${
                    taskOutput?.status === 'ok' ? 'bg-emerald-50 text-emerald-800' :
                    taskOutput?.status === 'error' ? 'bg-red-50 text-red-800' :
                    'bg-brand-50 text-brand-800'
                  }`}>
                    {applying && !taskOutput && (
                      <div className="w-3.5 h-3.5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
                    )}
                    {taskOutput?.status === 'ok' ? '✓ Completed successfully' :
                     taskOutput?.status === 'error' ? '✗ Completed with errors' :
                     taskStatus?.state === 'PENDING' ? 'Queued…' :
                     taskStatus?.state === 'STARTED' ? 'Running…' :
                     'Processing…'}
                    {taskId && <span className="ml-auto text-xs text-gray-400 font-mono">{taskId.slice(0, 8)}</span>}
                  </div>

                  {taskOutput?.reason && (
                    <div className="bg-red-50 px-4 py-3 text-sm text-red-700 font-mono">
                      {taskOutput.reason}
                    </div>
                  )}

                  {taskOutput?.stderr && (
                    <pre className="bg-gray-900 text-red-300 px-4 py-3 text-xs font-mono overflow-auto max-h-32 whitespace-pre-wrap">
                      {taskOutput.stderr}
                    </pre>
                  )}

                  {/* Parsed Salt JSON output */}
                  {parsedOutput.length > 0 ? (
                    <div className="divide-y divide-gray-200">
                      {parsedOutput.map(({ minion, states: stateResults }) => {
                        const failed = stateResults.filter((s) => !s.result).length
                        const changed = stateResults.filter((s) => s.changes).length
                        return (
                          <div key={minion} className="border border-gray-200 dark:border-gray-700 rounded-lg mb-3 last:mb-0 overflow-hidden">
                            <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800 rounded-t-lg gap-3">
                              <span className="font-mono font-semibold text-gray-900 dark:text-gray-100 text-sm">{minion}</span>
                              <div className="flex items-center gap-2 ml-auto">
                                {failed > 0 && (
                                  <span className="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full font-medium">
                                    {failed} failed
                                  </span>
                                )}
                                {changed > 0 && (
                                  <span className="text-xs px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-full font-medium">
                                    {changed} changed
                                  </span>
                                )}
                                <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">
                                  {stateResults.length - changed - failed} unchanged
                                </span>
                                <button
                                  onClick={() => navigator.clipboard.writeText(JSON.stringify(stateResults, null, 2))}
                                  className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600"
                                >
                                  Copy
                                </button>
                              </div>
                            </div>
                            <ul className="divide-y divide-gray-100">
                              {stateResults.map((sr) => (
                                <li
                                  key={sr.id}
                                  className={`flex items-start gap-3 px-4 py-2 text-sm ${
                                    !sr.result ? 'bg-red-50' : sr.changes ? 'bg-emerald-50' : ''
                                  }`}
                                >
                                  <span className={`text-base flex-shrink-0 mt-0.5 ${
                                    !sr.result ? 'text-red-500' : sr.changes ? 'text-emerald-600' : 'text-gray-300'
                                  }`}>
                                    {!sr.result ? '✗' : sr.changes ? '✓' : '·'}
                                  </span>
                                  <div className="flex-1 min-w-0">
                                    <p className="font-mono text-xs text-gray-700 truncate">{sr.id}</p>
                                    {sr.comment && (
                                      <p className="text-xs text-gray-500 mt-0.5 whitespace-pre-wrap">{sr.comment}</p>
                                    )}
                                  </div>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )
                      })}
                    </div>
                  ) : taskOutput?.stdout ? (
                    (() => {
                      let parsed: unknown = null
                      try { parsed = JSON.parse(taskOutput.stdout) } catch { /* not JSON */ }
                      if (parsed && typeof parsed === 'object') {
                        return (
                          <div className="divide-y divide-gray-200">
                            {Object.entries(parsed as Record<string, unknown>).map(([minion, result]) => (
                              <div key={minion} className="border border-gray-200 dark:border-gray-700 rounded-lg mb-3 last:mb-0 overflow-hidden">
                                <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800 rounded-t-lg">
                                  <span className="font-mono text-sm font-medium text-gray-900 dark:text-gray-100">{minion}</span>
                                  <button
                                    onClick={() => navigator.clipboard.writeText(JSON.stringify(result, null, 2))}
                                    className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600"
                                  >
                                    Copy
                                  </button>
                                </div>
                                <pre className="p-4 text-xs font-mono text-gray-800 dark:text-gray-200 overflow-auto max-h-64 bg-white dark:bg-gray-900 rounded-b-lg">
                                  {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
                                </pre>
                              </div>
                            ))}
                          </div>
                        )
                      }
                      return (
                        <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                          <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800">
                            <span className="font-mono text-sm font-medium text-gray-900 dark:text-gray-100">stdout</span>
                            <button
                              onClick={() => navigator.clipboard.writeText(taskOutput.stdout ?? '')}
                              className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600"
                            >
                              Copy
                            </button>
                          </div>
                          <pre className="bg-gray-900 text-gray-100 px-4 py-3 text-xs font-mono overflow-auto max-h-96 whitespace-pre-wrap rounded-b-lg">
                            {taskOutput.stdout}
                          </pre>
                        </div>
                      )
                    })()
                  ) : null}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
