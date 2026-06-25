import { memo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { ansibleApi, type BootstrapRunSummary } from '../../api/ansible'
import { formatIST } from '../../utils/time'
import { Pagination } from '../../components/Pagination'
import { LogPane } from '../../lib/LogPane'

export const BootstrapHistoryTab = memo(function BootstrapHistoryTab({ nodeId }: { nodeId: string }) {
  const [historyPage, setHistoryPage] = useState(1)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)

  const { data: bootstrapHistory } = useQuery({
    queryKey: ['bootstrap-history', nodeId, historyPage],
    queryFn: () => ansibleApi.bootstrapHistory(nodeId, historyPage),
    staleTime: 15_000,
    enabled: !!nodeId,
  })

  const { data: expandedRun } = useQuery({
    queryKey: ['bootstrap-run-detail', nodeId, expandedRunId],
    queryFn: () => ansibleApi.bootstrapRunDetail(nodeId, expandedRunId!),
    staleTime: 60_000,
    enabled: !!nodeId && !!expandedRunId,
  })

  return (
    <div role="tabpanel" id="tabpanel-bootstrap-history" aria-labelledby="tab-bootstrap-history" className="space-y-3">
      {!bootstrapHistory || bootstrapHistory.items.length === 0 ? (
        <p className="text-sm text-gray-500">No bootstrap runs recorded for this node.</p>
      ) : (
        bootstrapHistory.items.map((run: BootstrapRunSummary) => (
          <div key={run.id} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <button
              className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
              onClick={() =>
                setExpandedRunId(expandedRunId === run.id ? null : run.id)
              }
            >
              <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded ${
                run.status === 'completed'
                  ? 'bg-emerald-100 text-emerald-800'
                  : run.status === 'failed'
                  ? 'bg-red-100 text-red-800'
                  : 'bg-yellow-100 text-yellow-800'
              }`}>
                {run.status === 'completed' ? 'completed' : run.status === 'failed' ? 'failed' : 'running'}
              </span>
              <span className="text-sm text-gray-700 flex-1">
                {formatIST(run.started_at)}
                {run.finished_at && (
                  <span className="text-gray-400 ml-2">
                    — {formatDistanceToNow(new Date(run.started_at), { addSuffix: false })} duration
                  </span>
                )}
              </span>
              {run.target_ip && (
                <span className="text-xs text-gray-400">{run.target_ip}</span>
              )}
              <span className="text-xs text-gray-400">{expandedRunId === run.id ? '▲' : '▼'}</span>
            </button>
            {expandedRunId === run.id && (
              <div className="border-t border-gray-200 p-4 space-y-2">
                {run.error && (
                  <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2 font-mono">
                    {run.error}
                  </div>
                )}
                {run.has_stdout ? (
                  expandedRun?.id === run.id ? (
                    <div className="flex flex-col h-96">
                      <LogPane
                        raw={expandedRun.ansible_stdout ?? ''}
                        isLive={false}
                        emptyText="No stdout captured for this run."
                      />
                    </div>
                  ) : (
                    <p className="text-xs text-gray-500 italic">Loading logs…</p>
                  )
                ) : (
                  <p className="text-xs text-gray-500 italic">No stdout captured for this run.</p>
                )}
              </div>
            )}
          </div>
        ))
      )}
      {bootstrapHistory && bootstrapHistory.total > bootstrapHistory.per_page && (
        <Pagination
          page={historyPage}
          total={bootstrapHistory.total}
          perPage={bootstrapHistory.per_page}
          onPage={setHistoryPage}
        />
      )}
    </div>
  )
})
