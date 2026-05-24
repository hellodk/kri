import { create } from 'zustand'

interface FilterState {
  sidebarOpen: boolean
  nodeStatus: string
  driftSeverity: string
  executionStatus: string
  setSidebarOpen: (open: boolean) => void
  setNodeStatus: (status: string) => void
  setDriftSeverity: (severity: string) => void
  setExecutionStatus: (status: string) => void
  resetFilters: () => void
}

export const useFilterStore = create<FilterState>()((set) => ({
  sidebarOpen: true,
  nodeStatus: '',
  driftSeverity: '',
  executionStatus: '',
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setNodeStatus: (nodeStatus) => set({ nodeStatus }),
  setDriftSeverity: (driftSeverity) => set({ driftSeverity }),
  setExecutionStatus: (executionStatus) => set({ executionStatus }),
  resetFilters: () => set({ nodeStatus: '', driftSeverity: '', executionStatus: '' }),
}))
