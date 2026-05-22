import { create } from 'zustand'

interface SaltKeysState {
  pendingCount: number
  setPendingCount: (n: number) => void
}

export const useSaltKeysStore = create<SaltKeysState>()((set) => ({
  pendingCount: 0,
  setPendingCount: (n) => set({ pendingCount: n }),
}))
