import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'

interface AuthState {
  user: User | null
  hydrating: boolean
  setUser: (user: User) => void
  setHydrating: (v: boolean) => void
  clearAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      hydrating: false,
      setUser: (user) => set({ user, hydrating: false }),
      setHydrating: (v) => set({ hydrating: v }),
      clearAuth: async () => {
        const refreshToken = localStorage.getItem('refresh_token')
        const accessToken = localStorage.getItem('access_token')
        if (accessToken) {
          try {
            await fetch('/auth/logout', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${accessToken}`,
              },
              body: JSON.stringify({ refresh_token: refreshToken }),
            })
          } catch {
            // best-effort
          }
        }
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null, hydrating: false })
      },
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({ user: state.user }),
    }
  )
)
