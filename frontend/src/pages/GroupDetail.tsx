import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { groupsApi } from '../api/groups'
import { fleetApi } from '../api/fleet'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { useToastStore } from '../stores/toastStore'

export function GroupDetail() {
  const { groupId } = useParams<{ groupId: string }>()
  const [page, setPage] = useState(1)
  const [showAddNode, setShowAddNode] = useState(false)
  const [addNodeId, setAddNodeId] = useState('')
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

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

  // For the add-node selector: fetch all nodes to pick from
  const { data: allNodes } = useQuery({
    queryKey: ['nodes-for-group'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    enabled: showAddNode && group?.type === 'static',
    staleTime: 60_000,
  })

  const addMutation = useMutation({
    mutationFn: (nodeId: string) => groupsApi.addMember(groupId!, nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-members', groupId] })
      qc.invalidateQueries({ queryKey: ['group', groupId] })
      setAddNodeId('')
      setShowAddNode(false)
      toast('Node added to group')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeMutation = useMutation({
    mutationFn: (nodeId: string) => groupsApi.removeMember(groupId!, nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-members', groupId] })
      qc.invalidateQueries({ queryKey: ['group', groupId] })
      toast('Node removed from group')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (gLoading) return <Skeleton rows={4} />
  if (gError || !group) return <ErrorState message="Group not found" />

  const isStatic = group.type === 'static'
  const memberIds = new Set(members?.items.map((n) => n.id) ?? [])
  const nonMembers = allNodes?.items.filter((n) => !memberIds.has(n.id)) ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/groups" className="text-sm text-brand-600 hover:underline">← Groups</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{group.name}</h1>
        <span
          title={group.type === 'dynamic'
            ? 'Dynamic group: membership is resolved automatically from a predicate. Nodes cannot be added or removed manually.'
            : 'Static group: add and remove nodes manually using the controls below.'}
          className={`cursor-help text-xs px-2 py-0.5 rounded font-medium ${
            group.type === 'dynamic'
              ? 'bg-purple-100 text-purple-800 border border-purple-200'
              : 'bg-gray-100 text-gray-700 border border-gray-200'
          }`}
        >
          {group.type} ℹ
        </span>
      </div>

      {group.description && <p className="text-gray-600">{group.description}</p>}

      {group.predicate && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Predicate</p>
          <pre className="text-xs font-mono text-gray-700">{JSON.stringify(group.predicate, null, 2)}</pre>
          <p className="text-xs text-gray-400 mt-2">
            Members are resolved dynamically from this predicate — manual add/remove is not supported.
          </p>
        </div>
      )}

      {/* Members table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-700">
            Members <span className="text-gray-400 font-normal">({group.member_count})</span>
          </span>
          {isStatic && (
            <button
              onClick={() => setShowAddNode(!showAddNode)}
              className="text-sm text-brand-600 hover:text-brand-700 font-medium"
            >
              {showAddNode ? 'Cancel' : '+ Add node'}
            </button>
          )}
        </div>

        {/* Add node selector (static groups only) */}
        {showAddNode && isStatic && (
          <div className="px-4 py-3 bg-brand-50 border-b border-brand-100 flex items-center gap-3">
            <select
              value={addNodeId}
              onChange={(e) => setAddNodeId(e.target.value)}
              className="flex-1 text-sm bg-white border border-gray-300 text-gray-900 rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-600"
            >
              <option value="">Select a node…</option>
              {nonMembers.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.hostname ?? n.minion_id} — {n.ip_address ?? 'unknown IP'}
                </option>
              ))}
            </select>
            <button
              disabled={!addNodeId || addMutation.isPending}
              onClick={() => addMutation.mutate(addNodeId)}
              className="px-4 py-1.5 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 disabled:opacity-50"
            >
              {addMutation.isPending ? 'Adding…' : 'Add'}
            </button>
          </div>
        )}

        {mLoading ? (
          <Skeleton rows={5} />
        ) : members?.items.length === 0 ? (
          <div className="px-4 py-12 text-center text-gray-400 text-sm">
            {isStatic ? 'No members yet. Click "+ Add node" to add one.' : 'No nodes match this predicate.'}
          </div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">OS</th>
                  {isStatic && <th className="px-4 py-3 w-16"></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {members?.items.map((n) => (
                  <tr key={n.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link to={`/nodes/${n.id}`} className="text-brand-600 hover:underline font-medium">
                        {n.hostname ?? n.minion_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={n.status} /></td>
                    <td className="px-4 py-3"><DriftBadge score={n.drift_score} /></td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{n.os_version ?? '—'}</td>
                    {isStatic && (
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => removeMutation.mutate(n.id)}
                          disabled={removeMutation.isPending}
                          className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
                          title="Remove from group"
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {members && (
              <Pagination page={page} total={members.total} perPage={members.per_page} onPage={setPage} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
