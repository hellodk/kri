import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { groupsApi } from '../api/groups'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'

export function GroupDetail() {
  const { groupId } = useParams<{ groupId: string }>()
  const [page, setPage] = useState(1)

  const { data: group, isLoading: gLoading, isError: gError } = useQuery({
    queryKey: ['group', groupId],
    queryFn: () => groupsApi.get(groupId!),
    enabled: !!groupId,
  })

  const { data: members, isLoading: mLoading } = useQuery({
    queryKey: ['group-members', groupId, page],
    queryFn: () => groupsApi.members(groupId!, { page, per_page: 25 }),
    enabled: !!groupId,
    staleTime: 30_000,
  })

  if (gLoading) return <Skeleton rows={4} />
  if (gError || !group) return <ErrorState message="Group not found" />

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/groups" className="text-sm text-brand-600 hover:underline">← Groups</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{group.name}</h1>
        <span className={`text-xs px-2 py-0.5 rounded ${group.type === 'dynamic' ? 'bg-purple-100 text-purple-800' : 'bg-gray-100 text-gray-700'}`}>
          {group.type}
        </span>
      </div>
      {group.description && <p className="text-gray-600">{group.description}</p>}
      {group.predicate && (
        <div className="bg-gray-50 rounded p-3">
          <p className="text-xs text-gray-500 mb-1 uppercase">Predicate</p>
          <pre className="text-xs font-mono text-gray-700">{JSON.stringify(group.predicate, null, 2)}</pre>
        </div>
      )}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 text-sm font-medium text-gray-700">
          Members ({group.member_count})
        </div>
        {mLoading ? <Skeleton rows={5} /> : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">OS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {members?.items.map((n) => (
                  <tr key={n.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link to={`/nodes/${n.id}`} className="text-brand-600 hover:underline font-medium">
                        {n.hostname ?? n.minion_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={n.status} /></td>
                    <td className="px-4 py-3"><DriftBadge score={n.drift_score} /></td>
                    <td className="px-4 py-3 text-gray-600">{n.os_version ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {members && <Pagination page={page} total={members.total} perPage={members.per_page} onPage={setPage} />}
          </>
        )}
      </div>
    </div>
  )
}
