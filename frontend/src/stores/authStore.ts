import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'
import { api } from '../api/client'

interface AuthState {
  user: User | null
  hydrating: boolean
  _hasHydrated: boolean
  setUser: (user: User) => void
  setHydrating: (v: boolean) => void
  setHasHydrated: (v: boolean) => void
  clearAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      hydrating: false,
      _hasHydrated: false,
      setUser: (user) => set({ user, hydrating: false }),
      setHydrating: (v) => set({ hydrating: v }),
      setHasHydrated: (v) => set({ _hasHydrated: v }),
      clearAuth: async () => {
        const refreshToken = localStorage.getItem('refresh_token')
        await api
          .post('/api/v1/auth/logout', { refresh_token: refreshToken })
          .catch(() => {}) // best-effort — clear local state regardless
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null, hydrating: false })
      },
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({ user: state.user }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
