import { memo, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useToastStore } from '../../stores/toastStore'
import { isProtectedTarget } from './utils'
import type { NodeDetail as NodeDetailData } from '../../types'

export const ServicesTab = memo(function ServicesTab({
  node,
  nodeId,
}: {
  node: NodeDetailData
  nodeId: string
}) {
  const toast = useToastStore((s) => s.add)
  const [servicesLoading, setServicesLoading] = useState(false)
  const [servicesTaskId, setServicesTaskId] = useState<string | null>(null)
  const [servicesPolling, setServicesPolling] = useState(false)
  const [serviceList, setServiceList] = useState<Array<{ name: string; running: boolean }>>([])

  const { data: serviceTaskResult } = useQuery({
    queryKey: ['service-task', servicesTaskId],
    queryFn: () => api.get<{ task_id: string; state: string; result?: unknown }>(
      `/api/v1/ansible/tasks/${servicesTaskId}`
    ),
    enabled: !!servicesTaskId && servicesPolling,
    refetchInterval: (q) => {
      const s = q.state.data?.state
      return (s === 'PENDING' || s === 'STARTED') ? 2000 : false
    },
  })

  useEffect(() => {
    if (!serviceTaskResult || serviceTaskResult.state !== 'SUCCESS') return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- updating service list from polled task result; refactor tracked in #380 follow-up
    setServicesPolling(false)
    try {
      const ret = (serviceTaskResult.result as { return?: [Record<string, unknown>] })?.return?.[0]
      if (!ret) return
      // Prefer the known minion_id key; fall back to first value for resilience
      const minionData = (node?.minion_id && ret[node.minion_id])
        ? ret[node.minion_id]
        : Object.values(ret)[0]
      if (Array.isArray(minionData)) {
        setServiceList((minionData as string[]).sort().map(name => ({ name, running: true })))
      }
    } catch { /* parse error */ }
  }, [serviceTaskResult])

  async function fetchServices() {
    if (!nodeId) return
    setServicesLoading(true)
    try {
      const resp = await api.get<{ task_id: string }>(`/api/v1/nodes/${nodeId}/services`)
      setServicesTaskId(resp.task_id)
      setServicesPolling(true)
      toast('Service list queued')
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Failed to fetch services', 'error')
    } finally {
      setServicesLoading(false)
    }
  }

  async function requestServiceAction(svcName: string, actionType: 'service_start' | 'service_stop' | 'service_restart' | 'service_disable' | 'service_enable') {
    if (!nodeId) return
    try {
      const resp = await api.post<{ status: string; message: string }>(`/api/v1/nodes/${nodeId}/actions`, {
        action_type: actionType,
        params: { service: svcName, minion_id: node?.minion_id },
      })
      toast(resp.message || `${actionType} requested`)
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Action failed', 'error')
    }
  }

  return (
    <div role="tabpanel" id="tabpanel-services" aria-labelledby="tab-services" className="bg-white border border-gray-200 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-900">Services</h3>
        <button
          onClick={fetchServices}
          disabled={servicesLoading || servicesPolling}
          className="px-3 py-1.5 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          {servicesLoading ? 'Loading…' : servicesPolling ? '⟳ Fetching…' : serviceList.length > 0 ? '↺ Refresh' : '↺ Load'}
        </button>
      </div>

      <div className="rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th scope="col" className="text-left py-2.5 px-3 text-gray-600 font-medium">Service</th>
              <th scope="col" className="text-center py-2.5 px-3 text-gray-600 font-medium">State</th>
              <th scope="col" className="text-center py-2.5 px-3 text-gray-600 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {serviceList.length > 0
              ? serviceList.map(svc => {
                  const prot = isProtectedTarget(svc.name)
                  return (
                  <tr key={svc.name} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                    <td className="py-2 px-3 text-gray-700 font-mono text-xs truncate max-w-[200px]">{svc.name}</td>
                    <td className="py-2 px-3 text-center">
                      {/* Salt service.get_all returns the list of installed services,
                          not their live run state, so we must not assert "running" (#666). */}
                      <span
                        title="Salt lists installed services; live running state is not polled here"
                        className="px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600"
                      >installed</span>
                    </td>
                    <td className="py-2 px-3 text-center">
                      <div className="flex items-center justify-center gap-1">
                        <button onClick={() => requestServiceAction(svc.name, 'service_start')}
                          className="px-2 py-0.5 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50">Start</button>
                        <button onClick={() => requestServiceAction(svc.name, 'service_restart')}
                          className="px-2 py-0.5 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50">Restart</button>
                        <button onClick={() => requestServiceAction(svc.name, 'service_stop')}
                          disabled={prot}
                          aria-label={prot ? `Stop ${svc.name} — disabled: protected service` : `Stop ${svc.name}`}
                          title={prot ? 'Protected service — cannot be controlled remotely' : undefined}
                          className="px-2 py-0.5 text-xs bg-white border border-red-200 text-red-600 rounded hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed">Stop</button>
                        <button onClick={() => requestServiceAction(svc.name, 'service_disable')}
                          disabled={prot}
                          aria-label={prot ? `Disable ${svc.name} — disabled: protected service` : `Disable ${svc.name}`}
                          title={prot ? 'Protected service — cannot be controlled remotely' : undefined}
                          className="px-2 py-0.5 text-xs bg-white border border-red-200 text-red-600 rounded hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed">Disable</button>
                        <button onClick={() => requestServiceAction(svc.name, 'service_enable')}
                          className="px-2 py-0.5 text-xs bg-white border border-emerald-200 text-emerald-700 rounded hover:bg-emerald-50">Enable</button>
                      </div>
                      {prot && (
                        <p className="mt-1 text-[11px] text-amber-700">
                          Protected service — remote Stop/Disable are blocked.
                        </p>
                      )}
                    </td>
                  </tr>
                  )
                })
              : (
                  <tr>
                    <td colSpan={3} className="py-8 text-center text-sm text-gray-600">
                      {servicesPolling ? (
                        <span>Fetching service list…</span>
                      ) : (
                        <span>Click Load to fetch services via Salt.<br/>
                          <span className="text-xs">Start/Restart execute immediately. Stop/Disable require email approval.</span>
                        </span>
                      )}
                    </td>
                  </tr>
                )
            }
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-xs text-gray-600">
        Supports macOS (launchd) and Linux (systemd) nodes via Salt service module.
      </div>
    </div>
  )
})
