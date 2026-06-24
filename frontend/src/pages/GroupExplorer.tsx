import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { groupsApi } from '../api/groups'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Pagination } from '../components/Pagination'
import { formatLocalDate } from '../utils/time'

export function GroupExplorer() {
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState<'static' | 'dynamic'>('static')
  const [predicate, setPredicate] = useState('{"and": []}')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)
  const [deletingGroup, setDeletingGroup] = useState<{ id: string; name: string } | null>(null)
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['groups', page],
    queryFn: () => groupsApi.list({ page, per_page: 25 }),
    staleTime: 30_000,
  })

  const deleteMutation = useMutation({
    mutationFn: (groupId: string) => groupsApi.delete(groupId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      groupsApi.create({
        name,
        description: description || undefined,
        type,
        predicate: type === 'dynamic' ? JSON.parse(predicate) : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['groups'] })
      setShowForm(false)
      setName('')
      setDescription('')
      setPredicate('{"and": []}')
    },
  })

  // Bulk select helpers
  const allIds = data?.items.map((g) => g.id) ?? []
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id))
  const someSelected = allIds.some((id) => selected.has(id))
  const indeterminate = someSelected && !allSelected

  function toggleAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(allIds))
  }

  function toggleOne(id: string) {
    const next = new Set(selected)
    if (next.has(id)) { next.delete(id) } else { next.add(id) }
    setSelected(next)
  }

  function bulkDelete() {
    if (selected.size === 0) return
    setBulkDeleteConfirm(true)
  }

  async function confirmBulkDelete() {
    setBulkDeleteConfirm(false)
    const count = selected.size
    setBulkDeleting(true)
    await Promise.all([...selected].map((id) => groupsApi.delete(id)))
    setBulkDeleting(false)
    setSelected(new Set())
    qc.invalidateQueries({ queryKey: ['groups'] })
    toast(`Deleted ${count} group${count === 1 ? '' : 's'}`)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Groups</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700"
        >
          {showForm ? 'Cancel' : 'New Group'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={(e) => { e.preventDefault(); createMutation.mutate() }}
          className="bg-white rounded-lg border border-gray-200 p-4 space-y-4"
        >
          <h3 className="font-medium text-gray-700">Create Group</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Name</label>
              <input required value={name} onChange={(e) => setName(e.target.value)}
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Type</label>
              <select value={type} onChange={(e) => setType(e.target.value as 'static' | 'dynamic')}
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5">
                <option value="static">Static</option>
                <option value="dynamic">Dynamic</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
              className="w-full text-sm border border-gray-300 rounded px-2 py-1.5" />
          </div>
          {type === 'dynamic' && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                {'Predicate (JSON) — e.g. {"and":[{"key":"env","value":"prod"}]}'}
              </label>
              <textarea value={predicate} onChange={(e) => setPredicate(e.target.value)} rows={3}
                className="w-full text-sm font-mono border border-gray-300 rounded px-2 py-1.5" />
            </div>
          )}
          <div className="flex gap-2">
            <button type="submit" disabled={createMutation.isPending}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:opacity-50">
              {createMutation.isPending ? 'Creating…' : 'Create'}
            </button>
            {createMutation.isError && (
              <p className="text-red-600 text-sm self-center">{(createMutation.error as Error).message}</p>
            )}
          </div>
        </form>
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? <Skeleton rows={6} /> : isError ? (
          <ErrorState message="Failed to load groups" retry={refetch} />
        ) : (
          <>
            {/* Bulk action bar */}
            {selected.size > 0 && (
              <div className="flex items-center flex-wrap gap-2 px-4 py-2 bg-red-50 border-b border-red-200">
                <span className="text-sm font-medium text-red-700">{selected.size} group{selected.size === 1 ? '' : 's'} selected</span>
                <button
                  onClick={bulkDelete}
                  disabled={bulkDeleting}
                  className="px-3 py-1 bg-red-600 text-white text-xs font-medium rounded-lg hover:bg-red-700 disabled:opacity-50"
                >
                  {bulkDeleting ? 'Deleting…' : 'Delete selected'}
                </button>
                <button
                  onClick={() => setSelected(new Set())}
                  className="text-xs text-red-600 hover:text-red-800 ml-1"
                >
                  Clear selection
                </button>
              </div>
            )}

            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                  <th className="pl-4 py-3 w-8">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      ref={(el) => { if (el) el.indeterminate = indeterminate }}
                      onChange={toggleAll}
                      className="accent-brand-600 cursor-pointer"
                    />
                  </th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Members</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3 w-16"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((g) => (
                  <tr key={g.id} className={`hover:bg-gray-50 ${selected.has(g.id) ? 'bg-red-50/40' : ''}`}>
                    <td className="pl-4 py-3 w-8">
                      <input
                        type="checkbox"
                        checked={selected.has(g.id)}
                        onChange={() => toggleOne(g.id)}
                        className="accent-brand-600 cursor-pointer"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/groups/${g.id}`} className="text-brand-600 hover:underline font-medium">{g.name}</Link>
                      {g.description && <p className="text-xs text-gray-400">{g.description}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${g.type === 'dynamic' ? 'bg-purple-100 text-purple-800' : 'bg-gray-100 text-gray-700'}`}>
                        {g.type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{g.member_count}</td>
                    <td className="px-4 py-3 text-gray-500">{formatLocalDate(g.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setDeletingGroup({ id: g.id, name: g.name })}
                        disabled={deleteMutation.isPending || bulkDeleting}
                        className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && <Pagination page={page} total={data.total} perPage={data.per_page} onPage={setPage} />}
          </>
        )}
      </div>
      {bulkDeleteConfirm && (
        <ConfirmDialog
          title={`Delete ${selected.size} group${selected.size === 1 ? '' : 's'}?`}
          message="This cannot be undone. All selected groups will be permanently deleted."
          confirmLabel="Delete"
          destructive
          onConfirm={confirmBulkDelete}
          onCancel={() => setBulkDeleteConfirm(false)}
        />
      )}
      {deletingGroup && (
        <ConfirmDialog
          title={`Delete group "${deletingGroup.name}"?`}
          message="This cannot be undone."
          confirmLabel="Delete"
          destructive
          onConfirm={() => { deleteMutation.mutate(deletingGroup.id); setDeletingGroup(null) }}
          onCancel={() => setDeletingGroup(null)}
        />
      )}
    </div>
  )
}
