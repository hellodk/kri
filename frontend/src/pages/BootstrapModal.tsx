import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'

interface Props {
  onClose: () => void
}

const STATUS_LABEL: Record<string, { label: string; colour: string }> = {
  pending:      { label: 'Queued',   colour: 'text-gray-500' },
  bootstrapping:{ label: 'Running…', colour: 'text-brand-600' },
  completed:    { label: 'Done ✓',   colour: 'text-emerald-700' },
  failed:       { label: 'Failed',   colour: 'text-red-700' },
}

export function BootstrapModal({ onClose }: Props) {
  const [minionId, setMinionId] = useState('')
  const [targetIp, setTargetIp] = useState('')
  const [nodeId, setNodeId] = useState<string | null>(null)
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  const bootstrapMutation = useMutation({
    mutationFn: () => ansibleApi.bootstrap(minionId, targetIp),
    onSuccess: (data) => {
      setNodeId(data.node_id)
      toast('Bootstrap started')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const { data: statusData } = useQuery({
    queryKey: ['bootstrap-status', nodeId],
    queryFn: () => ansibleApi.bootstrapStatus(nodeId!),
    enabled: !!nodeId,
    refetchInterval: (query) => {
      const s = query.state.data?.bootstrap_status
      return (s === 'pending' || s === 'bootstrapping') ? 3000 : false
    },
  })

  useEffect(() => {
    if (statusData?.bootstrap_status === 'completed') {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    }
  }, [statusData?.bootstrap_status, qc])

  const status = statusData?.bootstrap_status
  const { label, colour } = STATUS_LABEL[status ?? 'pending'] ?? STATUS_LABEL.pending

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-bold text-gray-900">Bootstrap Mac Mini</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {!nodeId ? (
          <form onSubmit={(e) => { e.preventDefault(); bootstrapMutation.mutate() }} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Minion ID <span className="text-gray-400 font-normal">(hostname, e.g. mac-mini-01)</span>
              </label>
              <input
                required
                value={minionId}
                onChange={(e) => setMinionId(e.target.value)}
                placeholder="mac-mini-01"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">IP address</label>
              <input
                required
                value={targetIp}
                onChange={(e) => setTargetIp(e.target.value)}
                placeholder="10.0.1.11"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
              />
            </div>
            <p className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-lg p-3">
              Make sure Remote Login (SSH) is enabled on the Mac Mini before running bootstrap.
            </p>
            <div className="flex gap-3 pt-2">
              <button type="button" onClick={onClose}
                className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button type="submit" disabled={bootstrapMutation.isPending}
                className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                {bootstrapMutation.isPending ? 'Starting…' : 'Bootstrap'}
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
              <div className={`text-sm font-semibold ${colour}`}>{label}</div>
              <div className="text-sm text-gray-600 flex-1">{minionId} @ {targetIp}</div>
              {(status === 'pending' || status === 'bootstrapping') && (
                <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
              )}
            </div>

            {statusData?.bootstrap_error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-mono">
                {statusData.bootstrap_error}
              </div>
            )}

            {status === 'completed' && (
              <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
                Bootstrap complete. The node will appear in the fleet dashboard once the Salt minion connects and reports its grains.
              </p>
            )}

            <button
              onClick={onClose}
              className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              {status === 'completed' || status === 'failed' ? 'Close' : 'Close (runs in background)'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
