import { api } from './client'

export interface SaltState {
  name: string
  display: string
  path: string
}

export interface StatesResponse {
  states: SaltState[]
  states_dir: string
}

export const saltOpsApi = {
  listStates: () =>
    api.get<StatesResponse>('/api/v1/salt/states'),

  apply: (state: string, minionIds: string[], pillar?: Record<string, string>) =>
    api.post<{ task_id: string }>('/api/v1/salt/apply', {
      state,
      minion_ids: minionIds,
      pillar: pillar ?? null,
    }),

  cmd: (fn: string, minionIds: string[], args?: string[]) =>
    api.post<{ task_id: string }>('/api/v1/salt/cmd', {
      function: fn,
      minion_ids: minionIds,
      args: args ?? null,
    }),
}
