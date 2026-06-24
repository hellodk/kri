import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'
import { api } from '../api/client'

interface AuthState {
  user: User | null
  hydrating: boolean
  _hasHydrated: boolean
  // JWT access token. Kept in memory only (never persisted by `partialize`) so it
  // cannot be lifted out of localStorage by an XSS payload (#786). The refresh
  // token still persists in localStorage so sessions survive a reload — a
  // deliberate tradeoff: a refresh token alone cannot call the API and is
  // revocable server-side.
  accessToken: string | null
  setUser: (user: User) => void
  setHydrating: (v: boolean) => void
  setHasHydrated: (v: boolean) => void
  setAccessToken: (token: string | null) => void
  clearAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      hydrating: false,
      _hasHydrated: false,
      accessToken: null,
      setUser: (user) => set({ user, hydrating: false }),
      setHydrating: (v) => set({ hydrating: v }),
      setHasHydrated: (v) => set({ _hasHydrated: v }),
      setAccessToken: (token) => set({ accessToken: token }),
      clearAuth: async () => {
        const refreshToken = localStorage.getItem('refresh_token')
        await api
          .post('/api/v1/auth/logout', { refresh_token: refreshToken })
          .catch(() => {}) // best-effort — clear local state regardless
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null, hydrating: false, accessToken: null })
      },
    }),
    {
      name: 'auth-store',
      // Only `user` is persisted — `accessToken` is intentionally excluded so the
      // JWT stays in memory (#786).
      partialize: (state) => ({ user: state.user }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)

/**
 * Read the current access token for non-React callers (api clients, WebSocket
 * setup). Prefers the in-memory store value and falls back to the legacy
 * localStorage key as a transition shim: token *writers* (LoginPage,
 * OidcCallbackPage) are owned elsewhere and still persist to localStorage.
 * Once those are updated to call `setAccessToken` and stop writing localStorage,
 * this fallback can be removed to fully close #786.
 */
export function getAccessToken(): string | null {
  const inMemory = useAuthStore.getState().accessToken
  if (inMemory) return inMemory
  return localStorage.getItem('access_token')
}

/** Store the access token in memory (does not persist to localStorage). */
export function setAccessToken(token: string | null): void {
  useAuthStore.getState().setAccessToken(token)
}
