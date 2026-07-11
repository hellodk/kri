import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Zap } from 'lucide-react'
import { saltOpsApi, type SaltState } from '../api/saltOps'
import { fleetApi } from '../api/fleet'
import { api } from '../api/client'
import { Skeleton } from '../components/Skeleton'
import { useToastStore } from '../stores/toastStore'
import { SaltPillarDialog } from './SaltPillarDialog'
import { fuzzyAny } from '../utils/fuzzy'

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
  const [showPillarDialog, setShowPillarDialog] = useState(false)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskOutput, setTaskOutput] = useState<{ status: string; stdout?: string; stderr?: string; reason?: string } | null>(null)
  const [applying, setApplying] = useState(false)
  const [showQuickInstall, setShowQuickInstall] = useState(false)
  const [quickPkgManager, setQuickPkgManager] = useState<'pip' | 'brew' | 'pkg'>('pip')
  const [quickPackage, setQuickPackage] = useState('')
  const [showHelp, setShowHelp] = useState(false)
  const [stateFilter, setStateFilter] = useState('')

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

  async function applyState(pillar: Record<string, string>, test: boolean) {
    if (!selectedState || selectedMinions.size === 0) return
    setApplying(true)
    setTaskOutput(null)
    setTaskId(null)
    try {
      const resp = await saltOpsApi.apply(
        selectedState.name,
        Array.from(selectedMinions),
        Object.keys(pillar).length > 0 ? pillar : undefined,
        test,
      )
      setTaskId(resp.task_id)
      toast(test
        ? `Dry-run "${selectedState.display}" queued — no changes will be applied`
        : `State "${selectedState.display}" queued`)
    } catch (e: unknown) {
      setApplying(false)
      toast(e instanceof Error ? e.message : 'Apply failed', 'error')
    }
  }

  function handleApplyClick() {
    if (!selectedState || selectedMinions.size === 0) return
    setShowPillarDialog(true)
  }

  async function runQuickInstall() {
    if (!quickPackage.trim() || selectedMinions.size === 0) return
    setApplying(true)
    setTaskOutput(null)
    setTaskId(null)
    const fn = quickPkgManager === 'pip' ? 'pip.install'
             : quickPkgManager === 'pkg' ? 'pkg.install'
             : 'cmd.run'
    const args = quickPkgManager === 'brew'
      ? ['brew install ' + quickPackage.trim()]
      : [quickPackage.trim()]
    try {
      const resp = await saltOpsApi.cmd(fn, Array.from(selectedMinions), args)
      setTaskId(resp.task_id)
      toast(`Installing ${quickPackage} via ${quickPkgManager}…`)
    } catch (e: unknown) {
      setApplying(false)
      toast(e instanceof Error ? e.message : 'Install failed', 'error')
    }
  }

  const parsedOutput = taskOutput?.stdout ? renderSaltOutput(taskOutput.stdout) : []

  // Fuzzy filter — matches if every char of the query appears in order in the state name/display
  function stateMatchesFilter(s: SaltState) {
    if (!stateFilter) return true
    const score = fuzzyAny([s.name, s.display], stateFilter)
    return score > 0
  }

  // When a filter is active, sort matching states by relevance score (best match first)
  function sortedFolderStates(states: SaltState[]): SaltState[] {
    if (!stateFilter) return states
    return [...states]
      .filter(stateMatchesFilter)
      .sort((a, b) => fuzzyAny([b.name, b.display], stateFilter) - fuzzyAny([a.name, a.display], stateFilter))
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Salt Ops</h1>
          <p className="text-sm text-gray-500 mt-1">Apply Salt states to fleet nodes.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowHelp((v) => !v)}
            className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
          >
            Help
          </button>
          <button
            onClick={() => setShowQuickInstall(true)}
            className="px-4 py-2 text-sm font-medium bg-white border border-gray-200 text-gray-700 rounded-lg hover:bg-gray-50 shadow-xs inline-flex items-center gap-1.5"
          >
            <Zap size={15} /> Quick Install
          </button>
        </div>
      </div>

      {/* Help panel */}
      {showHelp && (
        <div className="bg-blue-50 border-l-4 border-blue-500 rounded-lg px-5 py-4 text-sm text-blue-900 space-y-2">
          <p className="font-semibold">How to use Salt Ops</p>
          <ul className="space-y-1 ml-4 list-disc">
            <li><span className="font-mono">ml_tools.init</span> — dotted names map to files: <span className="font-mono">/srv/salt/states/ml_tools/init.sls</span></li>
            <li><strong>Pillar data</strong> — key-value pairs passed to states via <span className="font-mono">{'{{ pillar.get("key", "default") }}'}</span></li>
            <li><strong>Quick Install</strong> — install pip/brew/pkg packages without a state file</li>
            <li><strong>Targeting</strong> — select individual minions or "Select all" for fleet-wide</li>
          </ul>
        </div>
      )}

      {/* Quick Install modal */}
      {showQuickInstall && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => setShowQuickInstall(false)}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-gray-900 inline-flex items-center gap-1.5"><Zap size={17} /> Quick Install</h2>
              <button
                onClick={() => setShowQuickInstall(false)}
                className="text-gray-400 hover:text-gray-600 text-xl leading-none"
              >
                ✕
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Package manager</label>
                <select
                  value={quickPkgManager}
                  onChange={(e) => setQuickPkgManager(e.target.value as 'pip' | 'brew' | 'pkg')}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-brand-500"
                >
                  <option value="pip">pip</option>
                  <option value="brew">brew</option>
                  <option value="pkg">pkg</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Package name</label>
                <input
                  type="text"
                  placeholder="e.g. vllm or vllm==0.4.0"
                  value={quickPackage}
                  onChange={(e) => setQuickPackage(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') runQuickInstall() }}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-brand-500"
                />
              </div>
              <p className="text-xs text-gray-400">
                {selectedMinions.size === 0
                  ? '⚠ Select minions in the main panel first'
                  : `Will run on ${selectedMinions.size} minion${selectedMinions.size === 1 ? '' : 's'}`}
              </p>
            </div>
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setShowQuickInstall(false)}
                className="flex-1 py-2 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => { runQuickInstall(); setShowQuickInstall(false) }}
                disabled={!quickPackage.trim() || selectedMinions.size === 0 || applying}
                className="flex-1 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
              >
                {applying ? 'Installing…' : 'Install'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main two-panel layout: 40/60 */}
      <div className="flex gap-5 items-start">
        {/* Left: States browser — 40% */}
        <div className="w-2/5 bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden shrink-0">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-700 mb-2">Salt States</p>
            <input
              type="search"
              placeholder="Filter states…"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-500 bg-gray-50"
            />
            <p className="text-xs text-gray-400 mt-1.5">{statesData?.states_dir ?? '/srv/salt/states'}</p>
          </div>
          {statesLoading ? (
            <Skeleton rows={4} />
          ) : states.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">No .sls files found.</div>
          ) : (
            <ul className="py-2">
              {folders.map((folder) => {
                const folderStates = stateTree[folder]
                const filteredFolderStates = sortedFolderStates(folderStates)
                if (filteredFolderStates.length === 0) return null
                const isOpen = expandedFolders.has(folder) || !!stateFilter
                if (!folder) {
                  // Root-level states
                  return filteredFolderStates.map((s) => (
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
                      <span className="ml-auto text-xs text-gray-400">{filteredFolderStates.length}</span>
                    </button>
                    {isOpen && (
                      <ul>
                        {filteredFolderStates.map((s) => (
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

        {/* Right: Action panel — 60% */}
        <div className="flex-1 space-y-4">
          {/* Node selector — always visible */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-xs p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold text-gray-700">Target Nodes</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-400">{selectedMinions.size} of {nodes.length} selected</span>
                <button
                  onClick={toggleAll}
                  className="text-xs text-brand-600 hover:underline font-medium"
                >
                  {allSelected ? 'Deselect all' : 'Select all'}
                </button>
              </div>
            </div>
            {nodesLoading ? (
              <span className="text-sm text-gray-400">Loading…</span>
            ) : nodes.length === 0 ? (
              <p className="text-sm text-gray-400">No nodes registered.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {nodes.map((n) => {
                  const mid = n.minion_id ?? n.id
                  const checked = selectedMinions.has(mid)
                  return (
                    <button
                      key={mid}
                      onClick={() => toggleMinion(mid)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${
                        checked
                          ? 'bg-brand-50 border-brand-300 text-brand-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-full shrink-0 ${n.status === 'online' ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                      {n.hostname ?? n.minion_id}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Selected state + Apply, or empty state */}
          {selectedState ? (
            <div className="bg-white rounded-xl border border-gray-200 shadow-xs p-4">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono px-2 py-1 bg-brand-50 text-brand-700 rounded border border-brand-200">
                    {selectedState.display}
                  </span>
                  <span className="text-xs text-gray-400 font-mono">{selectedState.path}</span>
                </div>
                <button
                  onClick={handleApplyClick}
                  disabled={selectedMinions.size === 0 || applying}
                  className="px-5 py-2 bg-brand-600 text-white font-semibold text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50 transition-colors flex items-center gap-2"
                >
                  {applying && (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  )}
                  {applying ? '⏳ Applying…' : '▷ Apply State'}
                </button>
              </div>

              {/* Task status / output */}
              {(applying || taskOutput) && (
                <div className={`rounded-xl border overflow-hidden ${
                  taskOutput?.status === 'ok' ? 'border-emerald-200' :
                  taskOutput?.status === 'ok_test' ? 'border-amber-200' :
                  taskOutput?.status === 'error' ? 'border-red-200' :
                  'border-brand-200'
                }`}>
                  <div className={`px-4 py-3 flex items-center gap-2 text-sm font-medium ${
                    taskOutput?.status === 'ok' ? 'bg-emerald-50 text-emerald-800' :
                    taskOutput?.status === 'ok_test' ? 'bg-amber-50 text-amber-800' :
                    taskOutput?.status === 'error' ? 'bg-red-50 text-red-800' :
                    'bg-brand-50 text-brand-800'
                  }`}>
                    {applying && !taskOutput && (
                      <div className="w-3.5 h-3.5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
                    )}
                    {taskOutput?.status === 'ok' ? '✓ Completed successfully' :
                     taskOutput?.status === 'ok_test' ? '⚠ Dry-run completed — no changes applied' :
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
                          <div key={minion} className="border border-gray-200 rounded-lg mb-3 last:mb-0 overflow-hidden">
                            <div className="flex items-center justify-between px-4 py-2 bg-gray-50 rounded-t-lg gap-3">
                              <span className="font-mono font-semibold text-gray-900 text-sm">{minion}</span>
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
                                  className="text-xs text-gray-500 hover:text-gray-700 px-2 py-0.5 rounded border border-gray-200"
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
                                  <span className={`text-base shrink-0 mt-0.5 ${
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
                              <div key={minion} className="border border-gray-200 rounded-lg mb-3 last:mb-0 overflow-hidden">
                                <div className="flex items-center justify-between px-4 py-2 bg-gray-50 rounded-t-lg">
                                  <span className="font-mono text-sm font-medium text-gray-900">{minion}</span>
                                  <button
                                    onClick={() => navigator.clipboard.writeText(JSON.stringify(result, null, 2))}
                                    className="text-xs text-gray-500 hover:text-gray-700 px-2 py-0.5 rounded border border-gray-200"
                                  >
                                    Copy
                                  </button>
                                </div>
                                <pre className="p-4 text-xs font-mono text-gray-800 overflow-auto max-h-64 bg-white rounded-b-lg">
                                  {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
                                </pre>
                              </div>
                            ))}
                          </div>
                        )
                      }
                      return (
                        <div className="border border-gray-200 rounded-lg overflow-hidden">
                          <div className="flex items-center justify-between px-4 py-2 bg-gray-50">
                            <span className="font-mono text-sm font-medium text-gray-900">stdout</span>
                            <button
                              onClick={() => navigator.clipboard.writeText(taskOutput.stdout ?? '')}
                              className="text-xs text-gray-500 hover:text-gray-700 px-2 py-0.5 rounded border border-gray-200"
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
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 shadow-xs p-8 text-center">
              <div className="text-4xl mb-3 text-gray-300">▹</div>
              <p className="text-sm font-medium text-gray-700 mb-1">No state selected</p>
              <p className="text-xs text-gray-400">Choose a Salt state from the left panel to apply it to the selected nodes.</p>
            </div>
          )}
        </div>
      </div>

      {showPillarDialog && selectedState && (
        <SaltPillarDialog
          state={selectedState.display}
          minionIds={Array.from(selectedMinions)}
          onClose={() => setShowPillarDialog(false)}
          onConfirm={(pillar, test) => {
            setShowPillarDialog(false)
            applyState(pillar, test)
          }}
        />
      )}
    </div>
  )
}
