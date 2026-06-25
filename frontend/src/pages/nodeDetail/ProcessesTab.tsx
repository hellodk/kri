import { memo, useState, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { fleetApi } from '../../api/fleet'
import { api } from '../../api/client'
import { formatLocalDateTime } from '../../utils/time'
import { useToastStore } from '../../stores/toastStore'
import { fmtBytes, isProtectedTarget } from './utils'
import type { NodeDetail as NodeDetailData } from '../../types'

export const ProcessesTab = memo(function ProcessesTab({
  node,
  nodeId,
}: {
  node: NodeDetailData
  nodeId: string
}) {
  const toast = useToastStore((s) => s.add)
  const [processSort, setProcessSort] = useState<'cpu' | 'mem' | 'name'>('cpu')

  const procSortParam = processSort === 'cpu' ? 'cpu_pct' : 'mem_rss_bytes'
  const { data: processData, isFetching: processFetching, refetch: refetchProcesses } = useQuery({
    queryKey: ['process-stats', nodeId, procSortParam],
    queryFn: () => fleetApi.processStats(nodeId, { sort: procSortParam as 'cpu_pct' | 'mem_rss_bytes', limit: 250 }),
    enabled: !!nodeId,
    refetchInterval: 30_000,
  })
  const processes = processData?.processes ?? []

  const sortedProcesses = useMemo(() =>
    [...processes].sort((a, b) =>
      processSort === 'name' ? a.name.localeCompare(b.name) :
      processSort === 'cpu' ? (b.cpu_pct ?? -1) - (a.cpu_pct ?? -1) :
      (b.mem_rss_bytes ?? -1) - (a.mem_rss_bytes ?? -1)
    ), [processes, processSort])

  const processTableRef = useRef<HTMLDivElement>(null)
  const processVirtualizer = useVirtualizer({
    count: sortedProcesses.length,
    getScrollElement: () => processTableRef.current,
    estimateSize: () => 37,
    overscan: 10,
  })

  async function requestProcessAction(pid: string, name: string, actionType: 'process_stop' | 'process_suspend' | 'process_resume') {
    if (!nodeId) return
    try {
      const resp = await api.post<{ status: string; message: string }>(`/api/v1/nodes/${nodeId}/actions`, {
        action_type: actionType,
        params: { pid, name, minion_id: node?.minion_id },
      })
      toast(resp.message || `${actionType} requested`)
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Action failed', 'error')
    }
  }

  return (
    <div role="tabpanel" id="tabpanel-processes" aria-labelledby="tab-processes" className="bg-white border border-gray-200 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-gray-900">Processes</h3>
          {processData?.collected_at && (
            <span className="text-xs text-gray-500">
              as of {formatLocalDateTime(processData.collected_at, {
                day: '2-digit', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false,
              })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={processSort}
            onChange={e => setProcessSort(e.target.value as 'cpu' | 'mem' | 'name')}
            className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-hidden"
          >
            <option value="cpu">Sort: CPU%</option>
            <option value="mem">Sort: Mem%</option>
            <option value="name">Sort: Name</option>
          </select>
          <button
            onClick={() => refetchProcesses()}
            disabled={processFetching}
            className="px-3 py-1.5 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1"
          >
            {processFetching ? (
              <>
                <span className="w-3 h-3 border border-gray-400 border-t-transparent rounded-full animate-spin" />
                Refreshing…
              </>
            ) : '↺ Refresh'}
          </button>
        </div>
      </div>

      {processes.length > 0 ? (
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <div ref={processTableRef} className="overflow-y-auto" style={{ maxHeight: 480 }}>
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th scope="col" className="text-left py-2.5 px-3 text-gray-500 font-medium w-16">PID</th>
                  <th scope="col" className="text-left py-2.5 px-3 text-gray-500 font-medium">Name</th>
                  <th scope="col" className="text-left py-2.5 px-3 text-gray-500 font-medium w-24">User</th>
                  <th scope="col" className="text-right py-2.5 px-3 text-gray-500 font-medium w-16">CPU%</th>
                  <th scope="col" className="text-right py-2.5 px-3 text-gray-500 font-medium w-20">Mem%</th>
                  <th scope="col" className="text-right py-2.5 px-3 text-gray-500 font-medium w-24">Mem (RSS)</th>
                  <th scope="col" className="text-center py-2.5 px-3 text-gray-500 font-medium w-40">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(() => {
                  const virtualItems = processVirtualizer.getVirtualItems()
                  const totalSize = processVirtualizer.getTotalSize()
                  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0
                  const paddingBottom = virtualItems.length > 0 ? totalSize - virtualItems[virtualItems.length - 1].end : 0
                  return (
                    <>
                      {paddingTop > 0 && <tr><td colSpan={7} style={{ height: paddingTop }} /></tr>}
                      {virtualItems.map(vRow => {
                        const p = sortedProcesses[vRow.index]
                        const prot = isProtectedTarget(p.name)
                        return (
                          <tr key={p.pid} className={`hover:bg-gray-50 ${p.is_llm ? 'bg-indigo-50' : ''}`}>
                            <td className="py-2 px-3 font-mono text-gray-500">{p.pid}</td>
                            <td className="py-2 px-3 font-medium text-gray-900 max-w-[200px] truncate" title={p.cmdline ?? p.name}>
                              {p.name}
                              {p.is_llm && (
                                <span className="ml-1.5 px-1.5 py-0.5 text-[10px] rounded bg-indigo-100 text-indigo-700 font-semibold">LLM</span>
                              )}
                            </td>
                            <td className="py-2 px-3 text-gray-500 truncate max-w-[80px]">{p.username ?? '—'}</td>
                            <td className={`py-2 px-3 text-right font-mono ${(p.cpu_pct ?? 0) > 50 ? 'text-red-600 font-semibold' : (p.cpu_pct ?? 0) > 20 ? 'text-amber-600' : 'text-gray-700'}`}>
                              {(p.cpu_pct ?? 0).toFixed(1)}
                            </td>
                            <td className={`py-2 px-3 text-right font-mono ${(p.mem_pct ?? 0) > 20 ? 'text-red-600 font-semibold' : (p.mem_pct ?? 0) > 5 ? 'text-amber-600' : 'text-gray-700'}`}>
                              {(p.mem_pct ?? 0).toFixed(1)}
                            </td>
                            <td className="py-2 px-3 text-right font-mono text-gray-600">
                              {fmtBytes(p.mem_rss_bytes)}
                            </td>
                            <td className="py-2 px-3">
                              <div className="flex items-center justify-center gap-1">
                                <button onClick={() => requestProcessAction(String(p.pid), p.name, 'process_stop')}
                                  disabled={prot}
                                  title={prot ? 'Protected service — cannot be controlled remotely' : 'Stop (SIGTERM) — requires email approval'}
                                  className="px-2 py-0.5 text-xs bg-amber-50 border border-amber-200 text-amber-700 rounded hover:bg-amber-100 disabled:opacity-40 disabled:cursor-not-allowed">Stop</button>
                                <button onClick={() => requestProcessAction(String(p.pid), p.name, 'process_suspend')}
                                  disabled={prot}
                                  title={prot ? 'Protected service — cannot be controlled remotely' : 'Suspend (SIGSTOP) — requires email approval'}
                                  className="px-2 py-0.5 text-xs bg-gray-50 border border-gray-200 text-gray-700 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed">Suspend</button>
                                <button onClick={() => requestProcessAction(String(p.pid), p.name, 'process_resume')}
                                  className="px-2 py-0.5 text-xs bg-emerald-50 border border-emerald-200 text-emerald-700 rounded hover:bg-emerald-100"
                                  title="Resume (SIGCONT)">Resume</button>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                      {paddingBottom > 0 && <tr><td colSpan={7} style={{ height: paddingBottom }} /></tr>}
                    </>
                  )
                })()}
              </tbody>
            </table>
          </div>
          <div className="px-3 py-2 bg-gray-50 border-t border-gray-100 text-xs text-gray-400">
            {processes.length} processes · Stop/Suspend require email approval · Kill (SIGKILL) disabled
          </div>
        </div>
      ) : (
        <div className="text-center py-10 text-gray-400">
          {processFetching ? (
            <div className="space-y-2">
              <div className="w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
              <p className="text-sm">Loading process list…</p>
            </div>
          ) : (
            <p className="text-sm">No process telemetry yet — the node collector reports every ~30s.<br/>
              <span className="text-xs">Stop/Suspend require email approval. Kill (SIGKILL) is disabled.</span>
            </p>
          )}
        </div>
      )}
    </div>
  )
})
