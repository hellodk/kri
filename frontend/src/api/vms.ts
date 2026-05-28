import { api } from './client'

export interface TartVM {
  name: string
  state: string
  cpu: number | null
  memory: number | null
  source: string
}

export interface NodeVMsResponse {
  node_id: string
  minion_id: string | null
  vms: TartVM[]
  error?: string
}

export const vmsApi = {
  listNodeVMs: (nodeId: string) =>
    api.get<NodeVMsResponse>(`/api/v1/nodes/${nodeId}/vms`),
}
