import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'

export function SettingsPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [master, setMaster] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
  })

  useEffect(() => {
    if (data) {
      if (data.salt_master_address) setMaster(data.salt_master_address)
      if (data.ssh_bootstrap_username) setUsername(data.ssh_bootstrap_username)
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateSettings({
      salt_master_address: master || undefined,
      ssh_bootstrap_username: username || undefined,
      ssh_bootstrap_password: password || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      toast('Settings saved')
      setPassword('')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (isLoading) return <div className="p-6 text-gray-500">Loading…</div>

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure Salt master and SSH bootstrap credentials.</p>
      </div>

      {/* Salt Master */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-900">Salt Master</h2>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Master address (LAN IP or DNS)
          </label>
          <input
            type="text"
            value={master}
            onChange={(e) => setMaster(e.target.value)}
            placeholder="10.0.0.1 or salt.fleet.local"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
          />
          <p className="text-xs text-gray-400 mt-1">Salt minions will point to this address.</p>
        </div>
      </div>

      {/* SSH Bootstrap credentials */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-900">SSH Bootstrap Credentials</h2>
        <p className="text-sm text-gray-500">
          Used only for initial bootstrap via Ansible. All Mac Minis must share these credentials.
          After bootstrap, kri uses the controller SSH key for all future connections.
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">macOS admin username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="localadmin"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            macOS admin password
            <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted, not shown after save)</span>
          </label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank to keep existing"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 pr-16"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
            >
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
      </div>

      {/* Controller SSH public key */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-3">
        <h2 className="text-base font-semibold text-gray-900">Controller SSH Public Key</h2>
        <p className="text-sm text-gray-500">
          This key is deployed to all Mac Minis during bootstrap. Add it to existing nodes manually if needed.
        </p>
        {data?.controller_pubkey ? (
          <div className="relative">
            <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto text-gray-700 whitespace-pre-wrap break-all">
              {data.controller_pubkey}
            </pre>
            <button
              onClick={() => { navigator.clipboard.writeText(data.controller_pubkey!); toast('Copied') }}
              className="absolute top-2 right-2 text-xs text-gray-400 hover:text-gray-600 bg-white border border-gray-200 rounded px-2 py-0.5"
            >
              Copy
            </button>
          </div>
        ) : (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
            No keypair generated yet. Save settings once to generate the controller keypair.
          </p>
        )}
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="px-6 py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
