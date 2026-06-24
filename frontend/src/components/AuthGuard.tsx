import { useEffect, useRef } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore, setAccessToken } from '../stores/authStore'
import { authApi } from '../api/auth'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  // Prefer the in-memory token (#786); fall back to the legacy localStorage key
  // until token writers (LoginPage/OidcCallbackPage) migrate to setAccessToken.
  const storeToken = useAuthStore((s) => s.accessToken)
  const token = storeToken ?? localStorage.getItem('access_token')
  const user = useAuthStore((s) => s.user)
  const hydrating = useAuthStore((s) => s.hydrating)
  const _hasHydrated = useAuthStore((s) => s._hasHydrated)
  const setUser = useAuthStore((s) => s.setUser)
  const setHydrating = useAuthStore((s) => s.setHydrating)
  // Use a ref to prevent multiple concurrent /auth/me calls
  const fetchingRef = useRef(false)

  useEffect(() => {
    if (token && !user && !fetchingRef.current) {
      fetchingRef.current = true
      setHydrating(true)
      authApi
        .me()
        .then((me) => {
          setUser(me)
          fetchingRef.current = false
        })
        .catch(() => {
          setAccessToken(null)
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          setHydrating(false)
          fetchingRef.current = false
        })
    }
  }, [token, user, setUser, setHydrating])

  // Wait for Zustand persist to finish reading from localStorage before rendering anything.
  // Without this gate, the store briefly returns user=null before rehydration completes,
  // causing a blank-screen flash on every page load.
  if (!_hasHydrated) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
      </div>
    )
  }

  if (!token) return <Navigate to="/login" replace />
  if (hydrating || (token && !user)) return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
    </div>
  )
  return <>{children}</>
}
