import { memo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { executionsApi } from '../../api/executions'
import { playbooksApi, type AnsibleJob } from '../../api/playbooks'
import { Pagination } from '../../components/Pagination'
import { useJobEventStream } from '../../hooks/useJobEventStream'

export const ExecutionsTab = memo(function ExecutionsTab({ nodeId }: { nodeId: string }) {
  const [execPage, setExecPage] = useState(1)

  // Live push: server pushes ansible-job transitions; the lists below refetch on
  // push and only fall back to a slow 30s safety-net poll (#756).
  useJobEventStream({ enabled: !!nodeId })

  const { data: executions } = useQuery({
    queryKey: ['executions-node', nodeId, execPage],
    queryFn: () => executionsApi.list({ node_id: nodeId, page: execPage, per_page: 25 }),
    staleTime: 10_000,
    enabled: !!nodeId,
  })

  const { data: ansibleJobs } = useQuery({
    queryKey: ['ansible-jobs-node', nodeId],
    queryFn: () => playbooksApi.listJobs({ node_id: nodeId, per_page: 25 }),
    staleTime: 10_000,
    refetchInterval: 30_000,
    enabled: !!nodeId,
  })

  return (
    <div role="tabpanel" id="tabpanel-executions" aria-labelledby="tab-executions" className="space-y-4">
      {/* Ansible playbook runs for this node */}
      {(ansibleJobs ?? []).length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">▷ Ansible Playbook Runs</h3>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                <th scope="col" className="px-4 py-2">Playbook</th>
                <th scope="col" className="px-4 py-2">Status</th>
                <th scope="col" className="px-4 py-2">Started</th>
                <th scope="col" className="px-4 py-2">RC</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(ansibleJobs ?? []).map((j: AnsibleJob) => (
                <tr key={j.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link to={`/playbook-job/${j.id}`} className="text-brand-600 hover:underline">
                      {j.playbook}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      j.status === 'completed' ? 'bg-green-100 text-green-800' :
                      j.status === 'failed'    ? 'bg-red-100 text-red-800' :
                      j.status === 'running'   ? 'bg-blue-100 text-blue-800' :
                      'bg-gray-100 text-gray-700'
                    }`}>{j.status}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">
                    {j.started_at ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true }) : '—'}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">
                    {typeof j.rc === 'number'
                      ? <span className={j.rc === 0 ? 'text-green-600' : 'text-red-600'}>{j.rc}</span>
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Salt state runs for this node */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
          <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">⬡ Salt State Runs</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
              <th scope="col" className="px-4 py-3">Type</th>
              <th scope="col" className="px-4 py-3">Status</th>
              <th scope="col" className="px-4 py-3">Triggered By</th>
              <th scope="col" className="px-4 py-3">Started</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(executions?.items ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-500">
                  No salt state runs for this node yet.
                </td>
              </tr>
            )}
            {executions?.items.map((j) => (
              <tr key={j.id} className="hover:bg-gray-50">
                <td className="px-4 py-2 font-mono text-xs">
                  <Link to={`/executions/${j.id}`} className="text-brand-600 hover:underline">
                    {j.type}
                  </Link>
                </td>
                <td className="px-4 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    j.status === 'completed' ? 'bg-green-100 text-green-800' :
                    j.status === 'failed'    ? 'bg-red-100 text-red-800' :
                    'bg-yellow-100 text-yellow-800'
                  }`}>
                    {j.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-gray-600 text-xs">{j.triggered_by}</td>
                <td className="px-4 py-2 text-gray-500 text-xs">
                  {j.started_at ? formatDistanceToNow(new Date(j.started_at), { addSuffix: true }) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {executions && (
          <Pagination page={execPage} total={executions.total} perPage={executions.per_page} onPage={setExecPage} />
        )}
      </div>
    </div>
  )
})
