import { useQuery } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { api } from '../api/client'

function useSaltMasterProbe(address: string | null) {
  return useQuery({
    queryKey: ['salt-master-probe', address],
    enabled: !!address,
    queryFn: async () => {
      const res = await api.post<{ ok: boolean; latency_ms: number | null; error?: string }>(
        '/api/v1/settings/probe',
        { target: address, port: 8080 }
      )
      return res
    },
    refetchInterval: 60_000,
    retry: false,
  })
}

export function SaltMasterStatus() {
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
    staleTime: 30_000,
  })

  const address = settings?.salt_master_address ?? null
  const { data: probe, isLoading: probing } = useSaltMasterProbe(address)

  if (!address) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 border border-gray-200 text-sm">
        <span className="w-2 h-2 rounded-full bg-gray-300 flex-shrink-0" />
        <span className="text-gray-500">Salt master not configured</span>
      </div>
    )
  }

  const isOnline = probe?.ok === true
  const isOffline = probe?.ok === false
  const latency = probe?.latency_ms

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 rounded-lg border text-sm"
      style={{
        background: isOnline ? '#f0fdf4' : isOffline ? '#fef2f2' : '#f9fafb',
        borderColor: isOnline ? '#bbf7d0' : isOffline ? '#fecaca' : '#e5e7eb',
      }}
    >
      <span
        className={`w-2 h-2 rounded-full flex-shrink-0 ${
          probing
            ? 'bg-gray-300 animate-pulse'
            : isOnline
            ? 'bg-green-500'
            : isOffline
            ? 'bg-red-500'
            : 'bg-gray-300'
        }`}
      />
      <div className="min-w-0">
        <span
          className={`font-medium ${
            isOnline ? 'text-green-800' : isOffline ? 'text-red-800' : 'text-gray-600'
          }`}
        >
          Salt master
        </span>
        <span className="text-gray-500 ml-1.5 font-mono text-xs truncate">{address}</span>
      </div>
      {latency != null && (
        <span className="text-xs text-gray-400 ml-auto flex-shrink-0">{latency}ms</span>
      )}
      {isOffline && (
        <span className="text-xs text-red-600 ml-auto flex-shrink-0">unreachable</span>
      )}
    </div>
  )
}
