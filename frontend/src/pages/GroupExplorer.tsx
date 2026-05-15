import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { groupsApi } from '../api/groups'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { format } from 'date-fns'

export function GroupExplorer() {
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState<'static' | 'dynamic'>('static')
  const [predicate, setPredicate] = useState('{"and": []}')
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['groups', page],
    queryFn: () => groupsApi.list({ page, per_page: 25 }),
    staleTime: 30_000,
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
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Members</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data?.items.map((g) => (
                  <tr key={g.id} className="hover:bg-gray-50">
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
                    <td className="px-4 py-3 text-gray-500">{format(new Date(g.created_at), 'PP')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && <Pagination page={page} total={data.total} perPage={data.per_page} onPage={setPage} />}
          </>
        )}
      </div>
    </div>
  )
}
