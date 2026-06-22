import { useCallback, useEffect, useState } from 'react'
import { actionApi, type AgentAction } from '../api/agent'

/**
 * In-app approval surface for agent-proposed live actions (#714). Shows the
 * proposed tool + params + captured dry-run, and lets an operator approve and an
 * admin co-sign (> N targets). Execution always runs as the original operator.
 */
export function AgentApprovals() {
  const [actions, setActions] = useState<AgentAction[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await actionApi.list()
      setActions(res.actions)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  const act = async (id: string, kind: 'approve' | 'reject') => {
    setBusy(id)
    setError(null)
    try {
      await (kind === 'approve' ? actionApi.approve(id) : actionApi.reject(id))
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const pending = actions.filter((a) => a.status === 'pending' || a.status === 'awaiting_cosign')

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">Pending approvals ({pending.length})</span>
        <button onClick={() => void refresh()} className="text-xs text-blue-600 hover:text-blue-700">
          Refresh
        </button>
      </div>
      {loading && <p className="text-xs text-gray-400">Loading…</p>}
      {error && <p className="text-xs text-red-600">⚠ {error}</p>}
      {!loading && actions.length === 0 && (
        <p className="text-xs text-gray-400 text-center py-4">No agent-proposed actions.</p>
      )}
      {actions.map((a) => (
        <div key={a.id} className="border border-gray-200 rounded-lg p-3 text-xs space-y-1.5 bg-white/80">
          <div className="flex items-center gap-2">
            <span className="font-mono font-semibold text-gray-700">{a.tool_name}</span>
            <StatusBadge status={a.status} />
            {a.co_sign_required && (
              <span className="px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px]">
                co-sign ×2 ({a.target_count} targets)
              </span>
            )}
          </div>
          <pre className="bg-gray-50 rounded p-2 overflow-x-auto text-[11px] text-gray-600">
            {JSON.stringify(a.params, null, 2)}
          </pre>
          <div className="text-gray-400">
            by {a.requested_by}
            {a.approved_by && ` · approved ${a.approved_by}`}
            {a.co_signed_by && ` · co-signed ${a.co_signed_by}`}
          </div>
          {(a.status === 'pending' || a.status === 'awaiting_cosign') && (
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => void act(a.id, 'approve')}
                disabled={busy === a.id}
                className="px-2.5 py-1 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded"
              >
                {a.status === 'awaiting_cosign' ? 'Co-sign (admin)' : 'Approve'}
              </button>
              <button
                onClick={() => void act(a.id, 'reject')}
                disabled={busy === a.id}
                className="px-2.5 py-1 bg-gray-200 hover:bg-gray-300 disabled:opacity-50 text-gray-700 rounded"
              >
                Reject
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === 'executed'
      ? 'bg-green-100 text-green-700'
      : status === 'failed' || status === 'rejected' || status === 'expired'
        ? 'bg-red-100 text-red-700'
        : status === 'awaiting_cosign'
          ? 'bg-amber-100 text-amber-700'
          : 'bg-blue-100 text-blue-700'
  return <span className={`px-1.5 py-0.5 rounded text-[10px] ${color}`}>{status}</span>
}
